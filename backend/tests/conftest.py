"""Shared fixtures.

By default tests run on an in-memory SQLite database (fast, no setup).
Set TEST_DATABASE_URL to a PostgreSQL URL to run the same suite against PostgreSQL,
which is the authoritative target.
"""
import os
from collections.abc import Iterator

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret")

from sqlalchemy import create_engine, event  # noqa: E402

from app.models import Base  # noqa: E402

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite://")


def _build_engine() -> Engine:
    if TEST_DATABASE_URL.startswith("sqlite"):
        engine = create_engine(
            TEST_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    return create_engine(TEST_DATABASE_URL)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = _build_engine()
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """Each test runs in a transaction that is rolled back afterwards."""
    connection = engine.connect()
    trans = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()
