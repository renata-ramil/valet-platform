import secrets

import pytest
from app.audit import install_append_only_trigger
from app.db import Base, configure_sqlite_savepoints, get_db
from app.eta import reset_eta_provider
from app.events import reset_event_bus
from app.main import app
from app.models import Building, Car, InviteCode, Role, User
from app.ratelimit import reset_rate_limits
from app.security import hash_password
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture(autouse=True)
def _reset_event_bus():
    reset_event_bus()
    yield
    reset_event_bus()


@pytest.fixture(autouse=True)
def _reset_eta_provider():
    reset_eta_provider()
    yield
    reset_eta_provider()


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    configure_sqlite_savepoints(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        install_append_only_trigger(conn, "request_events")
        install_append_only_trigger(conn, "audit_events")
        install_append_only_trigger(conn, "ledger_entries")
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def building(db_session):
    b = Building(name="Harbor Tower", timezone="America/Los_Angeles")
    db_session.add(b)
    db_session.commit()
    db_session.refresh(b)
    return b


def make_invite(db_session, building_id: str, role: Role = Role.resident, max_uses: int = 1):
    invite = InviteCode(
        building_id=building_id,
        code=f"invite-{secrets.token_hex(6)}",
        role=role,
        max_uses=max_uses,
    )
    db_session.add(invite)
    db_session.commit()
    db_session.refresh(invite)
    return invite


def make_user(
    db_session, building_id: str, role: Role = Role.resident, email: str = "user@example.com"
):
    user = User(
        building_id=building_id,
        email=email,
        password_hash=hash_password("password123"),
        role=role,
        full_name="Test User",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def make_car(db_session, building_id: str, owner_id: str, plate: str = "ABC123"):
    car = Car(
        building_id=building_id,
        owner_id=owner_id,
        make="Honda",
        model="Civic",
        color="blue",
        license_plate=plate,
    )
    db_session.add(car)
    db_session.commit()
    db_session.refresh(car)
    return car
