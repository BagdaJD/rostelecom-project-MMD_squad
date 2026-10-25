"""Test environment and portable business checks; PostGIS has a separate integration suite."""

import os
import sys
from pathlib import Path

import pytest
from geoalchemy2 import Geometry
from sqlalchemy import Text, create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-0123456789")
os.environ.setdefault("TOTP_ENCRYPTION_KEY", "test-totp-key-not-for-production-0123456789")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://rtk:rtk@localhost:5432/rtk_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")


@pytest.fixture
def authenticated_session():
    """Business API tests use persisted MFA sessions; auth itself has separate HTTP tests."""
    from app.core.security import encrypt_secret, new_totp_secret
    from modules.auth import service as auth

    def create(session, user):
        user.totp_enabled = True
        user.totp_secret_encrypted = encrypt_secret(new_totp_secret())
        session.flush()
        tokens = auth._issue_tokens(session, user, None)
        session.commit()
        return tokens

    return create


@pytest.fixture
def business_db(monkeypatch):
    from app.models import Base

    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, Geometry):
                monkeypatch.setattr(column, "type", Text())
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session, engine
    finally:
        engine.dispose()
