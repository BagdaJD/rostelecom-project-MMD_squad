from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, DbSession
from app.models import Company, InvestmentProject, Notification, Tender
from app.schemas import CompanyOut, HeatCellOut, WhiteSpaceOut
from app.schemas.companies import CompanyCardOut, MetricOut
from modules.radar import service as radar
from modules.radar.companies import company_card
from modules.radar.metrics import metrics_for_company

router = APIRouter(tags=["radar"])


@router.get("/radar/insights")
def insights(
    session: DbSession,
    user: CurrentUser,
    region_id: int | None = None,
    industry_group: str | None = None,
    municipality: str | None = None,
    signal_type: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    from modules.radar.signals import insights as list_insights

    return list_insights(
        session,
        region_id=region_id,
        industry_group=industry_group,
        municipality=municipality,
        signal_type=signal_type,
        limit=limit,
        offset=offset,
    )
@router.get("/companies/{company_id}/score")
def company_score(company_id: int, session: DbSession, user: CurrentUser) -> dict:
    from fastapi import HTTPException

    from ingestion.persistence import saved_company_score

    if session.get(Company, company_id) is None:
        raise HTTPException(404, "Компания не найдена")
    return saved_company_score(session, company_id)


@router.get("/companies", response_model=list[CompanyOut])
def list_companies(
    session: DbSession,
    user: CurrentUser,
    region_id: int | None = None,
    industry_id: int | None = None,
    industry_group: str | None = None,
    municipality: str | None = None,
    q: str | None = Query(None, min_length=1, max_length=255),
    client_status: str | None = Query(None, pattern="^(active|prospect|unknown)$"),
    min_revenue: float | None = Query(None, ge=0),
    min_growth: float | None = Query(None, ge=-100),
    report_year: int | None = Query(None, ge=1900, le=2200),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[CompanyOut]:
    return radar.list_companies(
        session,
        region_id=region_id,
        industry_id=industry_id,
        client_status=client_status,
        min_revenue=min_revenue,
        industry_group=industry_group,
        municipality=municipality,
        q=q,
        min_growth=min_growth,
        report_year=report_year,
        limit=limit,
        offset=offset,
    )


@router.get("/companies/{company_id}", response_model=CompanyCardOut)
def card(company_id: int, session: DbSession, user: CurrentUser):
    result = company_card(session, company_id)
    if result is None:
        raise HTTPException(404, "Компания не найдена")
    return result


@router.get("/companies/{company_id}/metrics", response_model=list[MetricOut])
def metrics(company_id: int, session: DbSession, user: CurrentUser, metric_code: str | None = None):
    if session.get(Company, company_id) is None:
        raise HTTPException(404, "Компания не найдена")
    return [
        dict(row)
        for row in metrics_for_company(session, company_id)
        if metric_code is None or row["metric_code"] == metric_code
    ]


@router.get("/radar/heatmap", response_model=list[HeatCellOut])
def heatmap(
    session: DbSession,
    user: CurrentUser,
    region_id: int | None = None,
    industry_group: str | None = None,
    municipality: str | None = None,
    level: Literal["region", "municipality"] = "region",
    report_year: int | None = Query(None, ge=1900, le=2200),
    service_type: str | None = None,
) -> list[dict]:
    cells = radar.heatmap(
        session,
        region_id=region_id,
        industry_group=industry_group,
        municipality=municipality,
        level=level,
        report_year=report_year,
        service_type=service_type,
    )
    return [c.model_dump(mode="json") for c in cells]


@router.get("/radar/white-spaces", response_model=list[WhiteSpaceOut])
def white_spaces(
    session: DbSession,
    user: CurrentUser,
    region_id: int | None = None,
    industry_group: str | None = None,
    municipality: str | None = None,
    level: Literal["region", "municipality"] = "region",
    report_year: int | None = Query(None, ge=1900, le=2200),
    service_type: str | None = None,
) -> list[dict]:
    result = radar.white_spaces(
        session,
        region_id=region_id,
        industry_group=industry_group,
        municipality=municipality,
        level=level,
        report_year=report_year,
        service_type=service_type,
    )
    return [w.model_dump(mode="json") for w in result]


@router.get("/dashboard/summary")
def summary(session: DbSession, user: CurrentUser) -> dict:
    """Счётчики главного дашборда (ТЗ 11.3)."""
    return {
        "companies": session.scalar(select(func.count(Company.id))) or 0,
        "active_projects": session.scalar(
            select(func.count(InvestmentProject.id)).where(
                InvestmentProject.stage.in_(("design", "modernization", "construction"))
            )
        )
        or 0,
        "open_tenders": session.scalar(
            select(func.count(Tender.id)).where(
                Tender.status == "published", Tender.deadline_date >= date.today()
            )
        )
        or 0,
        "unread_notifications": session.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id, Notification.read_at.is_(None)
            )
        )
        or 0,
    }


def investments_unread(session: Session, user_id: int) -> list[Notification]:
    from modules.notifications import service as notifications

    return notifications.unread(session, user_id, limit=100)
