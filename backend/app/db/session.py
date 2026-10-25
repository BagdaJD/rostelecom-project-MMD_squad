"""Сессии и движок SQLAlchemy."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
    connect_args={
        "connect_timeout": settings.database_connect_timeout_sec,
        "options": "-csearch_path=public",
    },
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    """Зависимость FastAPI: одна сессия на запрос."""
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
