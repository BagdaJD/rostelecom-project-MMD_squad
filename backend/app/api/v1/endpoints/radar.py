from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, DbSession
from app.models import Company, InvestmentProject, Notification, Tender
from app.schemas import CompanyOut
from modules.investments import service as investments
from modules.radar import service as radar

router = APIRouter(tags=["radar"])


@router.get("/companies", response_model=list[CompanyOut])
def list_companies(
    session: DbSession,
    user: CurrentUser,
    region_id: int | None = None,
    industry_id: int | None = None,
    client_status: str | None = Query(None, pattern="^(active|prospect|unknown)$"),
    min_revenue: float | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
) -> list[CompanyOut]:
    return radar.list_companies(
        session,
        region_id=region_id,
        industry_id=industry_id,
        client_status=client_status,
        min_revenue=min_revenue,
        limit=limit,
        offset=offset,
    )


@router.get("/radar/heatmap")
def heatmap(session: DbSession, user: CurrentUser, region_id: int | None = None,
            industry_group: str | None = None) -> list[dict]:
    cells = radar.heatmap(
        session,
        region_id=region_id,
        industry_group=industry_group,
        active_projects=investments.active_projects_by_slice(session),
        open_tenders=investments.open_tenders_by_slice(session),
    )
    return [c.model_dump(mode="json") for c in cells]


@router.get("/radar/white-spaces")
def white_spaces(session: DbSession, user: CurrentUser, region_id: int | None = None,
                 industry_group: str | None = None) -> list[dict]:
    result = radar.white_spaces(
        session,
        region_id=region_id,
        industry_group=industry_group,
        active_projects=investments.active_projects_by_slice(session),
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
        ) or 0,
        "open_tenders": session.scalar(select(func.count(Tender.id))) or 0,
        "unread_notifications": len(investments_unread(session, user.id)),
    }


def investments_unread(session: Session, user_id: int) -> list[Notification]:
    from modules.notifications import service as notifications

    return notifications.unread(session, user_id, limit=100)
