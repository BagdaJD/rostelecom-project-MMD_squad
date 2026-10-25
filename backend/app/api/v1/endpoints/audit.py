from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.core.deps import AdminUser, DbSession
from app.models import AuditLog
from app.schemas import ORMModel

router = APIRouter(tags=["audit"])


class AuditOut(ORMModel):
    id: int
    user_id: int | None
    action: str
    object_type: str | None
    object_id: str | None
    before_hash: str | None
    after_hash: str | None
    ip: str | None
    created_at: datetime


@router.get("/audit", response_model=list[AuditOut])
def list_audit(
    session: DbSession,
    user: AdminUser,
    action: str | None = Query(None, max_length=64),
    user_id: int | None = Query(None, gt=0),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    statement = select(AuditLog)
    if action is not None:
        statement = statement.where(AuditLog.action == action)
    if user_id is not None:
        statement = statement.where(AuditLog.user_id == user_id)
    return session.scalars(statement.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).all()
