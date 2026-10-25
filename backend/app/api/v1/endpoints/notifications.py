from datetime import UTC

from fastapi import APIRouter, HTTPException, Query, status

from app.core.deps import CurrentUser, DbSession
from app.models import Notification
from app.schemas import NotificationOut
from modules.notifications import service as notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    session: DbSession,
    user: CurrentUser,
    unread_only: bool = True,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[NotificationOut]:
    if unread_only:
        return notifications.unread(session, user.id, limit=limit, offset=offset)
    from sqlalchemy import select

    return list(
        session.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )


@router.patch("/{notification_id}/read")
def mark_read(notification_id: int, session: DbSession, user: CurrentUser) -> dict:
    from datetime import datetime

    row = session.get(Notification, notification_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Уведомление не найдено")
    row.read_at = datetime.now(UTC)
    session.commit()
    return {"status": "read"}
