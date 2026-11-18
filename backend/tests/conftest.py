"""Shared fixtures.

By default tests run on an in-memory SQLite database (fast, no setup).
Set TEST_DATABASE_URL to a PostgreSQL URL to run the same suite against PostgreSQL,
which is the authoritative target.
"""
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret")
os.environ.setdefault("BCRYPT_ROUNDS", "4")  # fast hashing in tests only

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event, select, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.database import get_db  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Role, User  # noqa: E402
from app.models.enums import RoleCode  # noqa: E402
from app.seed.reference_data import seed_reference  # noqa: E402

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite://")
IS_POSTGRES = TEST_DATABASE_URL.startswith("postgresql")
TEST_PASSWORD = "Passw0rd!"
BACKEND_DIR = Path(__file__).resolve().parent.parent

postgres_only = pytest.mark.skipif(not IS_POSTGRES, reason="needs PostgreSQL (set TEST_DATABASE_URL)")


def reset_postgres_schema(eng: Engine) -> None:
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


def migrate_postgres(url: str) -> None:
    """Build the schema with the real Alembic migrations (incl. the ledger's append-only trigger),
    so a PostgreSQL run also proves the migrations match the models."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _build_engine() -> Engine:
    if TEST_DATABASE_URL.startswith("sqlite"):
        engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    return create_engine(TEST_DATABASE_URL)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = _build_engine()
    if IS_POSTGRES:
        reset_postgres_schema(eng)
        migrate_postgres(TEST_DATABASE_URL)
    else:
        Base.metadata.drop_all(eng)
        Base.metadata.create_all(eng)
    with Session(eng) as s:  # reference data shared by all tests (committed once)
        seed_reference(s)
        s.commit()
    yield eng
    if IS_POSTGRES:
        reset_postgres_schema(eng)
    else:
        Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """Each test runs in a transaction that is rolled back afterwards."""
    connection = engine.connect()
    trans = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    """API client sharing the test's session, so everything rolls back after the test."""

    def _override() -> Iterator[Session]:
        # Each request gets its own SAVEPOINT: a failing request rolls back only its own
        # changes (like production's per-request transaction), not the test's fixtures.
        nested = db.begin_nested()
        try:
            yield db
            db.flush()
            nested.commit()
        except Exception:
            nested.rollback()
            raise

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    counter = {"n": 0}

    def _make(role: RoleCode, username: str | None = None, active: bool = True) -> User:
        counter["n"] += 1
        role_row = db.scalars(select(Role).where(Role.code == role)).one()
        user = User(
            username=username or f"{role.value.lower()}_{counter['n']}",
            full_name=f"Test {role.value.title()} {counter['n']}",
            password_hash=hash_password(TEST_PASSWORD),
            role_id=role_row.id,
            is_active=active,
        )
        db.add(user)
        db.flush()
        db.refresh(user)
        return user

    return _make


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role.code.value)}"}


@pytest.fixture
def as_role(make_user) -> Callable[[RoleCode], dict[str, str]]:
    """`headers = as_role(RoleCode.ADMIN)` -> auth headers for a fresh user of that role."""
    return lambda role: auth_headers(make_user(role))
