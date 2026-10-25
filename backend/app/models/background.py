"""Durable events, export tasks and prepared read/model artifacts."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, LargeBinary, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DomainEvent(Base):
    __tablename__ = "domain_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String(64), unique=True)
    module: Mapped[str] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(48))
    object_id: Mapped[int] = mapped_column()
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationReceipt(Base):
    __tablename__ = "notification_receipt"
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscription.id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[int] = mapped_column(ForeignKey("domain_event.id"), primary_key=True)


class BackgroundTask(Base):
    __tablename__ = "background_task"
    __table_args__ = (Index("ix_background_task_status_lease", "status", "lease_until"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_ref: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(String(255))


class DataRevision(Base):
    __tablename__ = "data_revision"
    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(default=0, server_default=text("0"))


class ReadModelSnapshot(Base):
    __tablename__ = "read_model_snapshot"
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    payload: Mapped[list] = mapped_column(JSON)
    source_revision: Mapped[int] = mapped_column()
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[str] = mapped_column(String(64))


class ModelArtifact(Base):
    __tablename__ = "model_artifact"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    signature: Mapped[str] = mapped_column(String(64))
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
