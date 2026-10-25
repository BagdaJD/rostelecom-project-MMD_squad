"""Durable, frequency-aware in-app delivery with atomic receipts and deduplication."""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select

from app.core.persistence import insert
from app.models import DomainEvent, Notification, NotificationReceipt, Subscription, User
from modules.auth.service import utc

FREQUENCIES = {"immediate": 0, "hourly": 3600, "daily": 86400, "weekly": 604800}


def matches(filters, payload):
    for key, value in (filters or {}).items():
        if value is None:
            continue
        if key == "q":
            if str(value).strip().casefold() not in str(payload.get("title", "")).casefold():
                return False
        elif key not in payload or payload[key] != value:
            return False
    return True


def dispatch(session, *, now=None):
    now = now or datetime.now(UTC)
    created = 0
    subscriptions = session.scalars(
        select(Subscription)
        .join(User, User.id == Subscription.user_id)
        .where(Subscription.is_active.is_(True), User.status == "active")
        .order_by(Subscription.id)
        .with_for_update(of=Subscription, skip_locked=True)
    ).all()
    for subscription in subscriptions:
        interval = FREQUENCIES.get(subscription.notify_frequency, 86400)
        if (
            subscription.last_dispatch_at
            and utc(subscription.last_dispatch_at) + timedelta(seconds=interval) > now
        ):
            continue
        while True:
            events = session.scalars(
                select(DomainEvent)
                .where(
                    DomainEvent.module == subscription.module,
                    DomainEvent.created_at >= subscription.created_at,
                    DomainEvent.created_at <= now,
                    ~exists(
                        select(NotificationReceipt.event_id).where(
                            NotificationReceipt.subscription_id == subscription.id,
                            NotificationReceipt.event_id == DomainEvent.id,
                        )
                    ),
                )
                .order_by(DomainEvent.id)
                .limit(250)
            ).all()
            if not events:
                break
            for event in events:
                if matches(subscription.filters_json, event.payload):
                    delivery = hashlib.sha256(
                        f"{subscription.user_id}:{event.event_key}".encode()
                    ).hexdigest()
                    result = session.execute(
                        insert(session, Notification)
                        .values(
                            user_id=subscription.user_id,
                            type=event.event_type,
                            payload_json=event.payload,
                            related_object=f"{event.module}:{event.object_id}",
                            dedup_key=f"event:{event.event_key}",
                            delivery_key=delivery,
                            created_at=now,
                        )
                        .on_conflict_do_nothing(index_elements=["delivery_key"])
                    )
                    created += result.rowcount
                session.execute(
                    insert(session, NotificationReceipt)
                    .values(subscription_id=subscription.id, event_id=event.id)
                    .on_conflict_do_nothing(index_elements=["subscription_id", "event_id"])
                )
        subscription.last_dispatch_at = now
    session.flush()
    return created


def notify_new_projects(session, projects):
    from modules.notifications.events import project_event

    for project in projects:
        project_event(session, project)
    return dispatch(session)


def notify_new_tenders(session, tenders):
    from modules.notifications.events import tender_event

    for tender in tenders:
        tender_event(session, tender)
    return dispatch(session)


def unread(session, user_id, limit=50, offset=0):
    return list(
        session.scalars(
            select(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .order_by(Notification.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
