import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request, status

from app.settings import settings

# In-memory sliding-window limiter. Good enough for a single-process API; a
# multi-worker deployment would need a shared store (Redis) instead.
_hits: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def reset_rate_limits() -> None:
    with _lock:
        _hits.clear()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def check_rate_limit(key: str, limit: int, window_seconds: float) -> None:
    now = time.monotonic()
    with _lock:
        hits = _hits[key]
        cutoff = now - window_seconds
        while hits and hits[0] < cutoff:
            hits.pop(0)
        if len(hits) >= limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests, slow down")
        hits.append(now)


def rate_limit(bucket: str, limit: int, window_seconds: float):
    # Dependency factory: a stricter, named limit on top of the global
    # per-IP middleware limit, for sensitive endpoints like login or
    # TOTP verification
    def _check(request: Request) -> None:
        key = f"{bucket}:{_client_ip(request)}"
        check_rate_limit(key, limit, window_seconds)

    return _check


DEFAULT_LIMIT = 120
DEFAULT_WINDOW_SECONDS = 60.0


def _allowed_origins() -> set[str]:
    return {o.strip() for o in settings.cors_origins.split(",") if o.strip()}


async def global_rate_limit_middleware(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        key = f"global:{_client_ip(request)}"
        try:
            check_rate_limit(key, DEFAULT_LIMIT, DEFAULT_WINDOW_SECONDS)
        except HTTPException as exc:
            from fastapi.responses import JSONResponse

            response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            # Returning directly here skips CORSMiddleware, which only
            # decorates responses that reach it through call_next. Without
            # these headers the browser reports a confusing CORS failure
            # instead of the real, readable 429 - adding them by hand so a
            # rate-limited client sees the actual error
            origin = request.headers.get("origin")
            if origin and origin in _allowed_origins():
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers["Vary"] = "Origin"
            return response
    return await call_next(request)
