"""Пользователи, сессии, подписки, provenance и аудит (ТЗ 6.5)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    login: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # admin | analyst | manager — проверка прав на сервере (ТЗ 13).
    role: Mapped[str] = mapped_column(String(16), default="manager")
    totp_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_codes_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active")
    failed_login_count: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(Base):
    __tablename__ = "refresh_token"

    jti: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))


class PartialAuth(Base):
    """Промежуточное состояние: пароль верный, второй фактор не подтверждён."""

    __tablename__ = "partial_auth"

    token_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    scope: Mapped[str] = mapped_column(String(32), default="mfa_pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SavedFilter(Base):
    __tablename__ = "saved_filter"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    module: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    filters_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class Subscription(Base):
    __tablename__ = "subscription"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    module: Mapped[str] = mapped_column(String(32))  # tenders | investments
    filters_json: Mapped[dict] = mapped_column(JSON, default=dict)
    notify_frequency: Mapped[str] = mapped_column(String(16), default="daily")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Notification(Base):
    """Доставка — только in-app: SMTP в MVP не закладываем (ТЗ 3)."""

    __tablename__ = "notification"
    __table_args__ = (Index("ix_notification_user_read", "user_id", "read_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    type: Mapped[str] = mapped_column(String(48))
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    related_object: Mapped[str | None] = mapped_column(String(128))
    dedup_key: Mapped[str] = mapped_column(String(128), index=True)
    channel: Mapped[str] = mapped_column(String(16), default="in_app")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceRecord(Base):
    """Provenance каждой загрузки: воспроизводимость и аудит (критерий «чистота, логика»)."""

    __tablename__ = "source_record"
    __table_args__ = (Index("ix_source_source_external", "source", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(48), index=True)
    external_id: Mapped[str | None] = mapped_column(String(128))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    payload_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    # pending | processed | skipped | error
    processing_status: Mapped[str] = mapped_column(String(16), default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    license_note: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    object_type: Mapped[str | None] = mapped_column(String(64))
    object_id: Mapped[str | None] = mapped_column(String(64))
    before_hash: Mapped[str | None] = mapped_column(String(64))
    after_hash: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ScoringSnapshot(Base):
    """История скоринга: score привязан к версии модели и режиму расчёта."""

    __tablename__ = "scoring_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(16))  # company | region
    subject_id: Mapped[int] = mapped_column(index=True)
    score: Mapped[float | None] = mapped_column()
    factors_json: Mapped[list] = mapped_column(JSON, default=list)
    # heuristic | trained — обязателен в ответе API (ТЗ 8).
    scoring_mode: Mapped[str] = mapped_column(String(16), default="heuristic")
    model_version: Mapped[str] = mapped_column(String(48))
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
