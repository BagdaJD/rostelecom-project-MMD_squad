"""Радар присутствия: плотность,client_status, «белые пятна» (модуль radar)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, CompanyMetric, CustomerPresence, Industry, Region
from app.schemas import CompanyOut, HeatCellOut, WhiteSpaceOut
from ml.scoring import (
    PotentialInput,
    explain_white_space,
    is_white_space,
    quartile_cut,
    score_potential,
)

REVENUE = "revenue"
GROWTH_MIN_SHARE = 0.05


def latest_revenue(session: Session, company_ids: list[int]) -> dict[int, tuple[int, Decimal]]:
    """Последний доступный год выручки по каждой компании."""
    if not company_ids:
        return {}
    rows = session.execute(
        select(CompanyMetric.company_id, func.max(CompanyMetric.period_year))
        .where(
            CompanyMetric.company_id.in_(company_ids),
            CompanyMetric.metric_code == REVENUE,
            CompanyMetric.value.is_not(None),
        )
        .group_by(CompanyMetric.company_id)
    ).all()
    out: dict[int, tuple[int, Decimal]] = {}
    for cid, year in rows:
        value = session.scalar(
            select(func.max(CompanyMetric.value)).where(
                CompanyMetric.company_id == cid,
                CompanyMetric.metric_code == REVENUE,
                CompanyMetric.period_year == year,
            )
        )
        if value is not None:
            out[cid] = (year, value)
    return out


def revenue_yoy(session: Session, company_ids: list[int]) -> dict[int, float]:
    """Динамика выручки требует временного ряда — CompanyMetric (ТЗ 6.2)."""
    if not company_ids:
        return {}
    rows = session.execute(
        select(CompanyMetric.company_id, CompanyMetric.period_year, CompanyMetric.value)
        .where(
            CompanyMetric.company_id.in_(company_ids),
            CompanyMetric.metric_code == REVENUE,
            CompanyMetric.value.is_not(None),
        )
        .order_by(CompanyMetric.company_id, CompanyMetric.period_year)
    ).all()
    series: dict[int, list[tuple[int, Decimal]]] = {}
    for cid, year, value in rows:
        series.setdefault(cid, []).append((year, value))

    deltas: dict[int, float] = {}
    for cid, points in series.items():
        if len(points) < 2:
            continue
        prev, last = points[-2][1], points[-1][1]
        if prev:
            deltas[cid] = round((float(last) - float(prev)) / float(prev) * 100, 1)
    return deltas


def list_companies(
    session: Session,
    *,
    region_id: int | None = None,
    industry_id: int | None = None,
    client_status: str | None = None,
    min_revenue: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[CompanyOut]:
    stmt = select(Company)
    if region_id:
        stmt = stmt.where(Company.region_id == region_id)
    if industry_id:
        stmt = stmt.where(Company.industry_id == industry_id)
    if client_status:
        stmt = stmt.where(Company.client_status == client_status)
    companies = session.scalars(stmt.order_by(Company.name).limit(limit).offset(offset)).all()

    ids = [c.id for c in companies]
    revenue = latest_revenue(session, ids)
    dynamics = revenue_yoy(session, ids)

    result: list[CompanyOut] = []
    for company in companies:
        year_value = revenue.get(company.id)
        yoy = dynamics.get(company.id)
        if min_revenue is not None and (
            year_value is None or float(year_value[1]) < min_revenue
        ):
            continue
        result.append(
            CompanyOut(
                id=company.id,
                name=company.name,
                inn=company.inn,
                industry_id=company.industry_id,
                region_id=company.region_id,
                client_status=company.client_status,
                revenue_latest=year_value[1] if year_value else None,
                revenue_year=year_value[0] if year_value else None,
                revenue_yoy=yoy,
            )
        )
    return result


@dataclass
class Slice:
    region_id: int
    region_name: str
    industry_group: str
    companies_count: int
    revenue_sum: Decimal
    growing_count: int
    client_count: int
    center_lon: float | None = None
    center_lat: float | None = None


def _slices(session: Session, region_id: int | None, industry_group: str | None) -> list[Slice]:
    rows = session.execute(
        select(
            Company.region_id,
            Region.name,
            Industry.group,
            func.count(Company.id),
            func.coalesce(func.sum(CompanyMetric.value), 0),
            Region.center_lon,
            Region.center_lat,
        )
        .join(Region, Region.id == Company.region_id)
        .join(Industry, Industry.id == Company.industry_id)
        .outerjoin(
            CompanyMetric,
            (CompanyMetric.company_id == Company.id)
            & (CompanyMetric.metric_code == REVENUE)
            & (CompanyMetric.value.is_not(None)),
        )
        .where(Company.region_id.is_not(None))
        .group_by(Company.region_id, Region.name, Industry.group, Region.center_lon, Region.center_lat)
        .order_by(Company.region_id, Industry.group)
    ).all()

    out = []
    for rid, rname, group, count, revenue_sum, lon, lat in rows:
        if region_id and rid != region_id:
            continue
        if industry_group and group != industry_group:
            continue
        ids = session.scalars(
            select(Company.id).where(
                Company.region_id == rid,
                Company.industry_id.in_(
                    select(Industry.id).where(Industry.group == group)
                ),
            )
        ).all()
        dynamics = revenue_yoy(session, list(ids))
        clients = session.scalar(
            select(func.count(Company.id)).where(
                Company.region_id == rid,
                Company.industry_id.in_(select(Industry.id).where(Industry.group == group)),
                Company.client_status == "active",
            )
        )
        out.append(
            Slice(
                region_id=rid,
                region_name=rname,
                industry_group=group,
                companies_count=count,
                revenue_sum=Decimal(str(revenue_sum or 0)),
                growing_count=sum(1 for v in dynamics.values() if v / 100 >= GROWTH_MIN_SHARE),
                client_count=clients or 0,
                center_lon=float(lon) if lon is not None else None,
                center_lat=float(lat) if lat is not None else None,
            )
        )
    return out


def presence_score(session: Session, region_id: int, service_type: str | None = None) -> float:
    """0–100: покрытие услугами и число контрактов; нет данных → 0, не среднее."""
    stmt = select(
        func.coalesce(func.avg(CustomerPresence.coverage_percent), 0),
        func.coalesce(func.sum(CustomerPresence.contracts_count), 0),
    ).where(CustomerPresence.region_id == region_id)
    if service_type:
        stmt = stmt.where(CustomerPresence.service_type == service_type)
    coverage, contracts = session.execute(stmt).one()
    coverage = float(coverage or 0)
    contracts = float(contracts or 0)
    # Контракты нормализуются «на глаз» по диапазону демо-набора; заменять корпоративной базой.
    return round(min(coverage * 0.7 + min(contracts / 20, 1.0) * 100 * 0.3, 100.0), 1)


def heatmap(
    session: Session,
    *,
    region_id: int | None = None,
    industry_group: str | None = None,
    active_projects: dict[tuple[int, str], int] | None = None,
    open_tenders: dict[tuple[int, str], int] | None = None,
) -> list[HeatCellOut]:
    slices = _slices(session, region_id, industry_group)
    if not slices:
        return []

    projects = active_projects or {}
    tenders = open_tenders or {}
    inputs = {
        (s.region_id, s.industry_group): PotentialInput(
            revenue_sum=float(s.revenue_sum),
            revenue_sum_max=max(float(x.revenue_sum) for x in slices),
            growth_share=(s.growing_count / s.companies_count) if s.companies_count else 0.0,
            companies_count=s.companies_count,
            companies_count_max=max(x.companies_count for x in slices),
            active_projects=projects.get((s.region_id, s.industry_group), 0),
            active_projects_max=max(projects.values(), default=0),
            open_tenders=tenders.get((s.region_id, s.industry_group), 0),
            open_tenders_max=max(tenders.values(), default=0),
        )
        for s in slices
    }
    return [
        HeatCellOut(
            region_id=s.region_id,
            region_name=s.region_name,
            industry_group=s.industry_group,
            companies_count=s.companies_count,
            revenue_sum=s.revenue_sum,
            growth_share=round(s.growing_count / s.companies_count, 3) if s.companies_count else 0.0,
            potential_score=score_potential(inputs[(s.region_id, s.industry_group)]).score,
            presence_score=presence_score(session, s.region_id),
            longitude=s.center_lon,
            latitude=s.center_lat,
        )
        for s in slices
    ]


def white_spaces(
    session: Session,
    *,
    region_id: int | None = None,
    industry_group: str | None = None,
    active_projects: dict[tuple[int, str], int] | None = None,
) -> list[WhiteSpaceOut]:
    cells = heatmap(session, region_id=region_id, industry_group=industry_group,
                    active_projects=active_projects)
    if not cells:
        return []
    p_cut = quartile_cut([c.potential_score for c in cells], 0.75)
    presence_cut = quartile_cut([c.presence_score for c in cells], 0.25)

    result: list[WhiteSpaceOut] = []
    for cell in cells:
        if not is_white_space(cell.potential_score, cell.presence_score, p_cut, presence_cut):
            continue
        ids = session.scalars(
            select(Company.id).where(
                Company.region_id == cell.region_id,
                Company.industry_id.in_(
                    select(Industry.id).where(Industry.group == cell.industry_group)
                ),
            )
        ).all()
        dynamics = revenue_yoy(session, list(ids))
        avg_yoy = round(sum(dynamics.values()) / len(dynamics), 1) if dynamics else None
        slices = _slices(session, cell.region_id, cell.industry_group)
        client_count = slices[0].client_count if slices else 0
        result.append(
            WhiteSpaceOut(
                region_id=cell.region_id,
                region_name=cell.region_name,
                industry_group=cell.industry_group,
                potential_score=cell.potential_score,
                presence_score=cell.presence_score,
                explanation=explain_white_space(
                    companies_count=cell.companies_count,
                    client_count=client_count,
                    active_projects=(active_projects or {}).get((cell.region_id, cell.industry_group), 0),
                    revenue_yoy=avg_yoy,
                    coverage_percent=None,
                ),
            )
        )
    return sorted(result, key=lambda w: -w.potential_score)


def derive_client_status(has_presence: bool, has_demand_signal: bool) -> str:
    """Правило вывода статуса, а не модель (ТЗ 7): статус объясним и виден в легенде."""
    if has_presence:
        return "active"
    if has_demand_signal:
        return "prospect"
    return "unknown"
