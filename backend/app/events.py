import json
import queue
import threading
from collections import defaultdict, deque
from typing import Protocol

from app.settings import settings

REPLAY_BUFFER_SIZE = 50


class EventBus(Protocol):
    def publish(self, user_id: str, event: dict) -> None: ...

    def subscribe(self, user_id: str, last_event_id: int | None = None) -> "Subscription": ...

    def unsubscribe(self, user_id: str, subscription: "Subscription") -> None: ...


class Subscription:
    def __init__(self, q: "queue.Queue[tuple[int, dict]]"):
        self.queue = q

    def get(self, timeout: float) -> tuple[int, dict] | None:
        try:
            return self.queue.get(block=True, timeout=timeout)
        except queue.Empty:
            return None


class InProcessEventBus:
    """Thread-safe pub/sub within a single process. Used for tests and local dev."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = defaultdict(list)
        self._replay: dict[str, deque[tuple[int, dict]]] = defaultdict(
            lambda: deque(maxlen=REPLAY_BUFFER_SIZE)
        )
        self._next_id: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def publish(self, user_id: str, event: dict) -> None:
        with self._lock:
            self._next_id[user_id] += 1
            event_id = self._next_id[user_id]
            self._replay[user_id].append((event_id, event))
            subscribers = list(self._subscribers.get(user_id, []))
        for q in subscribers:
            q.put_nowait((event_id, event))

    def subscribe(self, user_id: str, last_event_id: int | None = None) -> Subscription:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers[user_id].append(q)
            backlog = list(self._replay.get(user_id, []))
        if last_event_id is not None:
            for event_id, event in backlog:
                if event_id > last_event_id:
                    q.put_nowait((event_id, event))
        return Subscription(q)

    def unsubscribe(self, user_id: str, subscription: Subscription) -> None:
        with self._lock:
            subscribers = self._subscribers.get(user_id, [])
            if subscription.queue in subscribers:
                subscribers.remove(subscription.queue)


class PostgresEventBus:
    """LISTEN/NOTIFY backed bus for the real deployment. Requires a Postgres database_url.

    Not exercised in this environment (no Postgres available); see docs/KNOWN-ISSUES.md.
    The in-process fan-out below still drives this process's own SSE subscribers;
    the NOTIFY call additionally lets other worker processes observe the change.
    """

    CHANNEL_PREFIX = "valet_user_"

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.replace("+psycopg", "")
        self._in_process = InProcessEventBus()

    def publish(self, user_id: str, event: dict) -> None:
        import psycopg

        safe_id = user_id.replace(":", "_").replace("-", "_")
        channel = f"{self.CHANNEL_PREFIX}{safe_id}"
        with psycopg.connect(self._database_url) as conn, conn.cursor() as cur:
            cur.execute(f"NOTIFY {channel}, %s", (json.dumps(event),))
            conn.commit()
        self._in_process.publish(user_id, event)

    def subscribe(self, user_id: str, last_event_id: int | None = None) -> Subscription:
        return self._in_process.subscribe(user_id, last_event_id)

    def unsubscribe(self, user_id: str, subscription: Subscription) -> None:
        self._in_process.unsubscribe(user_id, subscription)


_bus: InProcessEventBus | PostgresEventBus | None = None


def get_event_bus() -> InProcessEventBus | PostgresEventBus:
    global _bus
    if _bus is None:
        if settings.database_url.startswith("postgresql"):
            _bus = PostgresEventBus(settings.database_url)
        else:
            _bus = InProcessEventBus()
    return _bus


def reset_event_bus() -> None:
    global _bus
    _bus = None


def building_channel(building_id: str) -> str:
    # A shared channel the manager dashboard and valet queue subscribe to,
    # distinct from a resident's private per-user channel
    return f"building:{building_id}"
