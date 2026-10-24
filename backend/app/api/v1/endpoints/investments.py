from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, DbSession
from app.models import InvestmentProject, ProjectNeed, Subscription
from app.schemas import NeedOut, SubscriptionIn, TimelinePointOut
from ml.needs import contact_window
from modules.investments import service as investments

router = APIRouter(prefix="/investments", tags=["investments"])


@router.get("")
def list_projects(
    session: DbSession,
    user: CurrentUser,
    stage: str | None = None,
    industry_id: int | None = None,
    region_id: int | None = None,
    initiator_company_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    projects = investments.list_projects(
        session,
        stage=stage,
        industry_id=industry_id,
        region_id=region_id,
        initiator_company_id=initiator_company_id,
        limit=limit,
        offset=offset,
    )
    return [
        {
            "id": p.id,
            "title": p.title,
            "stage": p.stage,
            "planned_start": p.planned_start,
            "estimated_budget": p.estimated_budget,
            "region_id": p.region_id,
            "initiator_company_id": p.initiator_company_id,
            "source_url": p.source_url,
        }
        for p in projects
    ]


@router.get("/timeline", response_model=list[TimelinePointOut])
def timeline(session: DbSession, user: CurrentUser, region_id: int | None = None,
             industry_id: int | None = None, period: str = "month") -> list[TimelinePointOut]:
    return investments.timeline(session, region_id=region_id, industry_id=industry_id, period=period)


@router.get("/{project_id}")
def project_card(project_id: int, session: DbSession, user: CurrentUser) -> dict:
    project = session.get(InvestmentProject, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
    tenders = investments.linked_tenders(session, project_id)
    return {
        "id": project.id,
        "title": project.title,
        "description": project.description,
        "stage": project.stage,
        "planned_start": project.planned_start,
        "planned_end": project.planned_end,
        "estimated_budget": project.estimated_budget,
        "region_id": project.region_id,
        "initiator_company_id": project.initiator_company_id,
        "source_url": project.source_url,
        "contact_window": contact_window(project.stage),
        "tenders": [
            {
                "id": t.id,
                "title": t.title,
                "price": t.price,
                "deadline_date": t.deadline_date,
                "source_url": t.source_url,
            }
            for t in tenders
        ],
    }


@router.get("/{project_id}/needs", response_model=list[NeedOut])
def needs(project_id: int, session: DbSession, user: CurrentUser) -> list[NeedOut]:
    rows = session.scalars(select(ProjectNeed).where(ProjectNeed.project_id == project_id)).all()
    return [
        NeedOut(
            need_category=r.need_category,
            probability=float(r.probability) if r.probability is not None else None,
            evidence=r.evidence,
            rule_id=r.rule_id,
            model_version=r.model_version,
        )
        for r in rows
    ]


subscriptions_router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@subscriptions_router.get("")
def list_subscriptions(session: DbSession, user: CurrentUser) -> list[dict]:
    rows = session.scalars(select(Subscription).where(Subscription.user_id == user.id)).all()
    return [
        {"id": s.id, "module": s.module, "filters": s.filters_json,
         "notify_frequency": s.notify_frequency, "is_active": s.is_active}
        for s in rows
    ]


@subscriptions_router.post("")
def create_subscription(payload: SubscriptionIn, session: DbSession, user: CurrentUser) -> dict:
    subscription = Subscription(
        user_id=user.id,
        module=payload.module,
        filters_json=payload.filters,
        notify_frequency=payload.notify_frequency,
    )
    session.add(subscription)
    session.commit()
    return {"id": subscription.id, "status": "created"}


@subscriptions_router.delete("/{subscription_id}")
def delete_subscription(subscription_id: int, session: DbSession, user: CurrentUser) -> dict:
    subscription = session.get(Subscription, subscription_id)
    if subscription is None or subscription.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Подписка не найдена")
    session.delete(subscription)
    session.commit()
    return {"status": "deleted"}
