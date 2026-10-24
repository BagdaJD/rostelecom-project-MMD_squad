"""Подписки и уведомления: канал только in-app (модуль notifications)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InvestmentProject, Notification, Subscription, Tender
from modules.investments.service import matches_subscription


def _dedup_key(module: str, object_id: int, user_id: int) -> str:
    return f"{module}:{object_id}:u{user_id}"


def notify_new_projects(session: Session, projects: list[InvestmentProject]) -> int:
    """Плановая задача: новым проектам соответствуют подписки по тем же фильтрам, что и список."""
    created = 0
    subscriptions = list(session.scalars(select(Subscription).where(Subscription.is_active.is_(True))))
    for project in projects:
        for subscription in subscriptions:
            if subscription.module != "investments":
                continue
            if not matches_subscription(subscription.filters_json or {}, project):
                continue
            key = _dedup_key("investments", project.id, subscription.user_id)
            if session.scalar(select(Notification.id).where(Notification.dedup_key == key)):
                continue
            session.add(
                Notification(
                    user_id=subscription.user_id,
                    type="investment.new",
                    related_object=f"investment_project:{project.id}",
                    dedup_key=key,
                    payload_json={
                        "title": project.title,
                        "stage": project.stage,
                        "region_id": project.region_id,
                        "source_url": project.source_url,
                    },
                )
            )
            created += 1
    return created


def notify_new_tenders(session: Session, tenders: list[Tender]) -> int:
    created = 0
    subscriptions = list(
        session.scalars(
            select(Subscription).where(
                Subscription.is_active.is_(True), Subscription.module == "tenders"
            )
        )
    )
    for tender in tenders:
        for subscription in subscriptions:
            filters = subscription.filters_json or {}
            if filters.get("category") and filters["category"] != tender.category:
                continue
            key = _dedup_key("tenders", tender.id, subscription.user_id)
            if session.scalar(select(Notification.id).where(Notification.dedup_key == key)):
                continue
            session.add(
                Notification(
                    user_id=subscription.user_id,
                    type="tender.new",
                    related_object=f"tender:{tender.id}",
                    dedup_key=key,
                    payload_json={
                        "title": tender.title,
                        "price": float(tender.price) if tender.price else None,
                        "deadline_date": tender.deadline_date.isoformat() if tender.deadline_date else None,
                        "source_url": tender.source_url,
                    },
                )
            )
            created += 1
    return created


def unread(session: Session, user_id: int, limit: int = 50) -> list[Notification]:
    return list(
        session.scalars(
            select(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .order_by(Notification.id.desc())
            .limit(limit)
        )
    )
