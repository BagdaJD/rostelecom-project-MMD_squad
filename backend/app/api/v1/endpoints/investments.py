from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models import InvestmentProject, ProjectMilestone, ProjectNeed, SourceRecord, Subscription
from app.schemas import NeedOut, ProjectOut, TimelinePointOut
from app.schemas.companies import ProjectCardOut
from app.schemas.preferences import SubscriptionPatch, SubscriptionRequest, validate_filters
from ml.needs import contact_window
from modules.investments import service as investments

router = APIRouter(prefix="/investments", tags=["investments"])


@router.get("", response_model=list[ProjectOut])
def list_projects(
    session: DbSession,
    user: CurrentUser,
    stage: str | None = None,
    industry_id: int | None = None,
    region_id: int | None = None,
    initiator_company_id: int | None = None,
    municipality: str | None = None,
    q: str | None = Query(None, min_length=1, max_length=255),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    projects = investments.list_projects(
        session,
        stage=stage,
        industry_id=industry_id,
        region_id=region_id,
        initiator_company_id=initiator_company_id,
        limit=limit,
        offset=offset,
        municipality=municipality,
        q=q,
    )
    return [investments.project_view(p) for p in projects]


@router.get("/timeline", response_model=list[TimelinePointOut])
def timeline(
    session: DbSession,
    user: CurrentUser,
    region_id: int | None = None,
    industry_id: int | None = None,
    period: Literal["month", "quarter", "year"] = "month",
    municipality: str | None = None,
) -> list[TimelinePointOut]:
    return investments.timeline(
        session,
        region_id=region_id,
        industry_id=industry_id,
        period=period,
        municipality=municipality,
    )


@router.get("/{project_id}", response_model=ProjectCardOut)
def project_card(project_id: int, session: DbSession, user: CurrentUser) -> dict:
    project = session.get(InvestmentProject, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
    tenders = investments.linked_tenders(session, project_id)
    from modules.radar.companies import provenance

    source = session.get(SourceRecord, project.source_id) if project.source_id else None
    milestones = session.scalars(
        select(ProjectMilestone)
        .where(ProjectMilestone.project_id == project_id)
        .order_by(ProjectMilestone.planned_date, ProjectMilestone.id)
    ).all()
    warnings = []
    if project.start_precision == "year" or project.end_precision == "year":
        warnings.append("Даты источника заданы годами, точные дни и месяцы неизвестны")
    if project.stage_method != "source":
        warnings.append("Стадия оценена по описанию; текущее состояние работ не подтверждено")
    return {
        **investments.project_view(project).model_dump(),
        "description": project.description,
        "planned_end": project.planned_end if project.end_precision == "day" else None,
        "contact_window": contact_window(project.stage),
        "stage_evidence": project.stage_evidence,
        "provenance": [provenance(source)] if source else [],
        "warnings": warnings,
        "milestones": [
            {
                "id": m.id,
                "title": "Начало проекта"
                if m.stage == "planned_start"
                else "Плановый ввод"
                if m.stage == "planned_end"
                else m.stage,
                "date": m.planned_date if m.date_precision == "day" else None,
                "year": m.planned_date.year if m.planned_date else None,
                "date_precision": m.date_precision,
                "status": "planned",
                "source_url": m.evidence_url,
            }
            for m in milestones
        ],
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
    if session.get(InvestmentProject, project_id) is None:
        raise HTTPException(404, "Проект не найден")
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
def list_subscriptions(
    session: DbSession,
    user: CurrentUser,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    rows = session.scalars(
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .order_by(Subscription.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        {
            "id": s.id,
            "module": s.module,
            "filters": s.filters_json,
            "notify_frequency": s.notify_frequency,
            "is_active": s.is_active,
            "created_at": s.created_at,
            "last_dispatch_at": s.last_dispatch_at,
        }
        for s in rows
    ]


@subscriptions_router.post("")
def create_subscription(
    payload: SubscriptionRequest, session: DbSession, user: CurrentUser
) -> dict:
    subscription = Subscription(
        user_id=user.id,
        module=payload.module,
        filters_json=payload.filters,
        notify_frequency=payload.notify_frequency,
        created_at=datetime.now(UTC),
    )
    session.add(subscription)
    session.commit()
    return {"id": subscription.id, "status": "created"}


@subscriptions_router.patch("/{subscription_id}")
def patch_subscription(
    subscription_id: int, payload: SubscriptionPatch, session: DbSession, user: CurrentUser
):
    row = session.scalar(
        select(Subscription)
        .where(Subscription.id == subscription_id, Subscription.user_id == user.id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Подписка не найдена")
    values = payload.model_dump(exclude_unset=True)
    if any(value is None for value in values.values()):
        raise HTTPException(422, "Поля изменения не могут быть null")
    if "filters" in values:
        try:
            row.filters_json = validate_filters(row.module, values.pop("filters"))
        except ValueError as error:
            raise HTTPException(422, "Некорректные фильтры подписки") from error
    for name, value in values.items():
        setattr(row, name, value)
    row.last_dispatch_at = None
    session.commit()
    return {"id": row.id, "status": "updated"}


@subscriptions_router.delete("/{subscription_id}")
def delete_subscription(subscription_id: int, session: DbSession, user: CurrentUser) -> dict:
    subscription = session.get(Subscription, subscription_id)
    if subscription is None or subscription.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Подписка не найдена")
    session.delete(subscription)
    session.commit()
    return {"status": "deleted"}
