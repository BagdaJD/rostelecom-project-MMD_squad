"""Радар присутствия: плотность,client_status, «белые пятна» (модуль radar)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, CompanyMetric, CustomerPresence, Industry, Region, ScoringSnapshot
from app.schemas import CompanyOut, HeatCellOut, WhiteSpaceOut
from ml.geo_scoring import find_white_spaces
from ml.scoring import (
    PotentialInput,
    explain_white_space,
    score_potential,
)

REVENUE = "revenue"
GROWTH_MIN_SHARE = 0.05


def _revenue_series(session, company_ids):
    if not company_ids:
        return {}
    statement = (
        select(
            CompanyMetric.company_id,
            CompanyMetric.period_year,
            CompanyMetric.value,
        )
        .where(
            CompanyMetric.metric_code == REVENUE,
            CompanyMetric.value.is_not(None),
        )
        .order_by(
            CompanyMetric.company_id,
            CompanyMetric.period_year,
            CompanyMetric.fetched_at.desc(),
            CompanyMetric.id.desc(),
        )
    )
    series = {}
    # Регион содержит >65535 компаний — один IN превысит лимит bind-параметров PG.
    for start in range(0, len(company_ids), 10000):
        rows = session.execute(
            statement.where(CompanyMetric.company_id.in_(company_ids[start : start + 10000]))
        ).all()
        for cid, year, value in rows:
            series.setdefault(cid, {}).setdefault(year, value)
    return series


def latest_revenue(session: Session, company_ids: list[int]) -> dict[int, tuple[int, Decimal]]:
    """Последний доступный год выручки по каждой компании."""
    return {
        cid: (max(points), points[max(points)])
        for cid, points in _revenue_series(session, company_ids).items()
    }


def revenue_yoy(session: Session, company_ids: list[int]) -> dict[int, float]:
    """Динамика выручки требует временного ряда — CompanyMetric (ТЗ 6.2)."""
    deltas: dict[int, float] = {}
    for cid, points in _revenue_series(session, company_ids).items():
        year = max(points)
        prev, last = points.get(year - 1), points[year]
        if prev is not None and prev > 0:
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
        stmt = stmt.where(
            Company.region_id.in_(
                select(Region.id).where((Region.id == region_id) | (Region.parent_id == region_id))
            )
        )
    if industry_id:
        stmt = stmt.where(Company.industry_id == industry_id)
    if client_status:
        stmt = stmt.where(Company.client_status == client_status)
    companies = session.scalars(stmt.order_by(Company.name).limit(limit).offset(offset)).all()

    ids = [c.id for c in companies]
    revenue = latest_revenue(session, ids)
    dynamics = revenue_yoy(session, ids)
    snapshots = session.scalars(
        select(ScoringSnapshot)
        .where(
            ScoringSnapshot.subject_type == "company",
            ScoringSnapshot.subject_id.in_(ids),
        )
        .order_by(ScoringSnapshot.calculated_at.desc(), ScoringSnapshot.id.desc())
    ).all()
    scores = {}
    for snapshot in snapshots:
        scores.setdefault(snapshot.subject_id, snapshot.score)

    result: list[CompanyOut] = []
    for company in companies:
        year_value = revenue.get(company.id)
        yoy = dynamics.get(company.id)
        if min_revenue is not None and (year_value is None or float(year_value[1]) < min_revenue):
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
                score=scores.get(company.id),
            )
        )
    return result


@dataclass
class Slice:
    region_id: int
    region_name: str
    industry_group: str
    companies_count: int
    revenue_sum: Decimal | None
    growing_count: int
    client_count: int
    growth_available_count: int = 0
    center_lon: float | None = None
    center_lat: float | None = None


def _slices(session: Session, region_id: int | None, industry_group: str | None) -> list[Slice]:
    rows = session.execute(
        select(
            Company.region_id,
            Region.name,
            Industry.group,
            Company.id,
            Company.client_status,
            Region.center_lon,
            Region.center_lat,
        )
        .join(Region, Region.id == Company.region_id)
        .join(Industry, Industry.id == Company.industry_id)
        .where(Company.region_id.is_not(None))
        .order_by(Company.region_id, Industry.group)
    ).all()

    allowed = (
        set(
            session.scalars(
                select(Region.id).where((Region.id == region_id) | (Region.parent_id == region_id))
            ).all()
        )
        if region_id
        else None
    )
    grouped = {}
    for rid, rname, group, cid, status, lon, lat in rows:
        if allowed is not None and rid not in allowed:
            continue
        if industry_group and group != industry_group:
            continue
        grouped.setdefault((rid, rname, group, lon, lat), []).append((cid, status))
    all_ids = [cid for items in grouped.values() for cid, _ in items]
    latest, dynamics = latest_revenue(session, all_ids), revenue_yoy(session, all_ids)
    out = []
    for (rid, rname, group, lon, lat), items in grouped.items():
        ids = [cid for cid, _ in items]
        revenues = [latest[cid][1] for cid in ids if cid in latest]
        out.append(
            Slice(
                region_id=rid,
                region_name=rname,
                industry_group=group,
                companies_count=len(ids),
                revenue_sum=sum(revenues) if revenues else None,
                growing_count=sum(
                    dynamics[cid] / 100 >= GROWTH_MIN_SHARE for cid in ids if cid in dynamics
                ),
                client_count=sum(status == "active" for _, status in items),
                growth_available_count=sum(cid in dynamics for cid in ids),
                center_lon=float(lon) if lon is not None else None,
                center_lat=float(lat) if lat is not None else None,
            )
        )
    return out


def presence_score(
    session: Session, region_id: int, service_type: str | None = None
) -> float | None:
    """Только последнее подтверждённое покрытие, без синтетических контрактов."""
    stmt = (
        select(CustomerPresence)
        .where(
            CustomerPresence.region_id == region_id,
            CustomerPresence.is_synthetic.is_(False),
            CustomerPresence.source_id.is_not(None),
            CustomerPresence.coverage_percent.is_not(None),
        )
        .order_by(CustomerPresence.as_of_date.desc(), CustomerPresence.id.desc())
    )
    if service_type:
        stmt = stmt.where(CustomerPresence.service_type == service_type)
    rows = session.scalars(stmt).all()
    latest = {}
    for row in rows:
        latest.setdefault((row.municipality, row.service_type), float(row.coverage_percent))
    return round(sum(latest.values()) / len(latest), 2) if latest else None


def heatmap(
    session: Session,
    *,
    region_id: int | None = None,
    industry_group: str | None = None,
    active_projects: dict[tuple[int, str], int] | None = None,
    open_tenders: dict[tuple[int, str], int] | None = None,
) -> list[HeatCellOut]:
    slices = _slices(session, region_id, industry_group)
    # Пакетный pipeline сохраняет муниципальные срезы, в том числе только с проектами.
    snapshots = session.execute(
        select(ScoringSnapshot, Region)
        .join(Region, Region.id == ScoringSnapshot.subject_id)
        .where(ScoringSnapshot.subject_type == "region")
        .order_by(ScoringSnapshot.calculated_at.desc(), ScoringSnapshot.id.desc())
    ).all()
    cached = {}
    slice_map = {(s.region_id, s.industry_group): s for s in slices}
    for snapshot, region in snapshots:
        if region_id and region.id != region_id and region.parent_id != region_id:
            continue
        payload = snapshot.factors_json[0] if snapshot.factors_json else {}
        group = payload.get("industry")
        key = (region.id, group)
        if "potential_score" not in payload or key in cached:
            continue
        if industry_group and industry_group != group:
            continue
        current = slice_map.get(key)
        presence = presence_score(session, region.id)
        cached[key] = HeatCellOut(
            region_id=region.id,
            region_name=region.name,
            industry_group=group,
            companies_count=payload["companies_count"],
            revenue_sum=current.revenue_sum if current else None,
            growth_share=(current.growing_count / current.growth_available_count)
            if current and current.growth_available_count
            else None,
            potential_score=payload["potential_score"],
            presence_score=presence,
            longitude=float(region.center_lon) if region.center_lon is not None else None,
            latitude=float(region.center_lat) if region.center_lat is not None else None,
            data_quality=payload.get("data_quality"),
            model_version=snapshot.model_version,
            presence_status="known" if presence is not None else "insufficient_presence_data",
            aggregation_level=payload.get("aggregation_level"),
        )
    if not slices:
        return list(cached.values())

    projects = active_projects or {}
    tenders = open_tenders or {}
    inputs = {
        (s.region_id, s.industry_group): PotentialInput(
            revenue_sum=float(s.revenue_sum) if s.revenue_sum is not None else None,
            revenue_sum_max=max(float(x.revenue_sum or 0) for x in slices),
            growth_share=(s.growing_count / s.growth_available_count)
            if s.growth_available_count
            else None,
            companies_count=s.companies_count,
            companies_count_max=max(x.companies_count for x in slices),
            active_projects=projects.get((s.region_id, s.industry_group))
            if active_projects is not None
            else None,
            active_projects_max=max(projects.values(), default=0),
            open_tenders=tenders.get((s.region_id, s.industry_group))
            if open_tenders is not None
            else None,
            open_tenders_max=max(tenders.values(), default=0),
        )
        for s in slices
    }
    return [
        *cached.values(),
        *[
            HeatCellOut(
                region_id=s.region_id,
                region_name=s.region_name,
                industry_group=s.industry_group,
                companies_count=s.companies_count,
                revenue_sum=s.revenue_sum,
                growth_share=round(s.growing_count / s.growth_available_count, 3)
                if s.growth_available_count
                else None,
                potential_score=score_potential(inputs[(s.region_id, s.industry_group)]).score,
                presence_score=presence_score(session, s.region_id),
                longitude=s.center_lon,
                latitude=s.center_lat,
                data_quality="limited",
                presence_status="known"
                if presence_score(session, s.region_id) is not None
                else "insufficient_presence_data",
            )
            for s in slices
            if (s.region_id, s.industry_group) not in cached
        ],
    ]


def white_spaces(
    session: Session,
    *,
    region_id: int | None = None,
    industry_group: str | None = None,
    active_projects: dict[tuple[int, str], int] | None = None,
) -> list[WhiteSpaceOut]:
    cells = heatmap(
        session, region_id=region_id, industry_group=industry_group, active_projects=active_projects
    )
    comparison = find_white_spaces(
        [
            {
                "region_id": c.region_id,
                "industry": c.industry_group,
                "aggregation_level": c.aggregation_level or "region",
                "potential_score": c.potential_score,
                "presence_score": c.presence_score,
                "companies_count": c.companies_count,
                "projects_count": (active_projects or {}).get((c.region_id, c.industry_group), 0),
            }
            for c in cells
        ]
    )
    eligible = {(c["region_id"], c["industry"]) for c in comparison["results"]}

    result: list[WhiteSpaceOut] = []
    for cell in cells:
        if (cell.region_id, cell.industry_group) not in eligible:
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
                    active_projects=(active_projects or {}).get(
                        (cell.region_id, cell.industry_group), 0
                    ),
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
