"""Immutable event outbox written in the same transaction as imported facts."""

import hashlib
import json
from datetime import UTC, datetime

from app.core.persistence import insert
from app.models import Company, DomainEvent


def emit(session, module, object_id, event_type, version, payload, *, now=None):
    key = hashlib.sha256(f"{module}:{object_id}:{version}".encode()).hexdigest()
    payload = json.loads(json.dumps(payload, default=str))
    result = session.execute(
        insert(session, DomainEvent)
        .values(
            event_key=key,
            module=module,
            object_id=object_id,
            event_type=event_type,
            payload=payload,
            created_at=now or datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["event_key"])
    )
    return result.rowcount


def project_event(session, project, created=True):
    return emit(
        session,
        "investments",
        project.id,
        "investment.new" if created else "investment.changed",
        project.source_id,
        {
            "title": project.title,
            "stage": project.stage,
            "region_id": project.region_id,
            "industry_id": project.industry_id,
            "municipality": project.municipality,
            "initiator_company_id": project.initiator_company_id,
            "source_id": project.source_id,
            "source_url": project.source_url,
            "is_synthetic": project.is_synthetic,
        },
    )


def tender_event(session, tender, created=True):
    customer = (
        session.get(Company, tender.customer_company_id) if tender.customer_company_id else None
    )
    return emit(
        session,
        "tenders",
        tender.id,
        "tender.new" if created else "tender.changed",
        tender.source_id,
        {
            "title": tender.title,
            "price": tender.price,
            "deadline_date": tender.deadline_date,
            "category": tender.category,
            "region_id": customer.region_id if customer else None,
            "industry_id": customer.industry_id if customer else None,
            "status": tender.status,
            "source_url": tender.source_url,
            "source_id": tender.source_id,
        },
    )
