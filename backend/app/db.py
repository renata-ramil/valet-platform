from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.settings import settings


def configure_sqlite_savepoints(target_engine) -> None:
    """pysqlite's default transaction handling conflicts with SAVEPOINT
    nesting: releasing a savepoint silently behaves like a real commit
    instead of merging into the still-open outer transaction, which breaks
    any dry-run-then-rollback flow (see app.fleet_service.import_cars_csv).
    This is the exact fix SQLAlchemy's own documentation recommends. A
    no-op outside the sqlite dialect.
    """
    if target_engine.dialect.name != "sqlite":
        return

    @event.listens_for(target_engine, "connect")
    def _do_connect(dbapi_connection, connection_record):
        dbapi_connection.isolation_level = None

    # using IMMEDIATE, not a plain deferred BEGIN: a request that reads
    # before it writes (almost every one, since each starts by loading the
    # current user) starts its transaction as a reader, then has to upgrade
    # to a writer at its first INSERT or UPDATE. When several such sessions
    # try to upgrade at the same moment, SQLite treats that as a possible
    # deadlock and fails them immediately with "database is locked" instead
    # of retrying under busy_timeout. BEGIN IMMEDIATE takes the write lock
    # up front, so concurrent writers correctly queue and retry instead of
    # failing on first contact; reproduced directly against
    # app.fleet_service.create_car under 20 concurrent threads (fails most
    # of them with a plain BEGIN, 20/20 succeed with BEGIN IMMEDIATE)
    @event.listens_for(target_engine, "begin")
    def _do_begin(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")


def configure_sqlite_concurrency(target_engine) -> None:
    """Letting concurrent requests (several queries plus a couple of open SSE
    streams from the live UI) share one SQLite file without "database is
    locked" errors: WAL mode lets readers run alongside a writer, and a busy
    timeout makes a real conflict wait briefly and retry instead of failing
    immediately. Only matters for a real file-backed database; skipped for
    the test suite's own :memory: engine, which conftest.py builds directly
    (unaffected by this function). A no-op outside the sqlite dialect.
    """
    if target_engine.dialect.name != "sqlite":
        return

    @event.listens_for(target_engine, "connect")
    def _do_connect(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.close()


connect_args = (
    {"check_same_thread": False, "timeout": 10}
    if settings.database_url.startswith("sqlite")
    else {}
)
engine = create_engine(settings.database_url, connect_args=connect_args)
configure_sqlite_savepoints(engine)
configure_sqlite_concurrency(engine)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
