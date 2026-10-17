import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.ratelimit import global_rate_limit_middleware
from app.routers import (
    auth,
    billing,
    calendar,
    cars,
    events,
    manager,
    manager_billing,
    manager_fleet,
    requests,
    schedules,
    shifts,
    sms,
    suggestions,
    support,
    tickets,
    totp,
    valet,
    webhooks,
)
from app.security_headers import body_size_limit_middleware, security_headers_middleware
from app.settings import settings

logger = logging.getLogger("valet")


def create_app() -> FastAPI:
    app = FastAPI(title="Valet platform API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(security_headers_middleware)
    app.middleware("http")(global_rate_limit_middleware)
    app.middleware("http")(body_size_limit_middleware)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "Invalid request"})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Logging the real error server-side, never in the response body,
        # so clients cannot learn about internals (stack traces, file paths)
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.include_router(auth.router)
    app.include_router(totp.router)
    app.include_router(cars.router)
    app.include_router(manager.router)
    app.include_router(manager_fleet.router)
    app.include_router(manager_billing.router)
    app.include_router(billing.router)
    app.include_router(webhooks.router)
    app.include_router(requests.router)
    app.include_router(schedules.router)
    app.include_router(events.router)
    app.include_router(valet.router)
    app.include_router(shifts.router)
    app.include_router(tickets.router)
    app.include_router(suggestions.router)
    app.include_router(support.router)
    app.include_router(sms.router)
    app.include_router(calendar.router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "env": settings.app_env}

    return app


app = create_app()
