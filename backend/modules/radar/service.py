"""Consistent radar aggregates: one company per slice and one source per metric/year."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import case, func, literal, select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    CompanyMetric,
    CustomerPresence,
    Industry,
    InvestmentProject,
    Region,
    Tender,
)
from app.schemas import CompanyOut, HeatCellOut, WhiteSpaceOut
from ingestion.normalize import normalize_name
from ml.scoring import (
    PotentialInput,
    explain_white_space,
    is_white_space,
    quartile_cut,
    score_potential,
)
from modules.radar.metrics import financials

MODEL_VERSION = "radar-scoring-0.2"


def latest_revenue(session: Session, company_ids: list[int]) -> dict:
    data = financials()
    return {
        r.company_id: (r.revenue_year, r.revenue_latest)
        for r in session.execute(select(data).where(data.c.company_id.in_(company_ids)))
    }


def revenue_yoy(session: Session, company_ids: list[int]) -> dict[int, float]:
    data = financials()
    return {
        r.company_id: round(float(r.revenue_yoy), 1)
        for r in session.execute(select(data).where(data.c.company_id.in_(company_ids)))
        if r.revenue_yoy is not None
    }


def company_conditions(
    *,
    region_id=None,
    industry_id=None,
    industry_group=None,
    client_status=None,
    municipality=None,
    q=None,
):
    result = []
    for column, value in (
        (Company.region_id, region_id),
        (Company.industry_id, industry_id),
        (Company.client_status, client_status),
        (Company.municipality, municipality),
    ):
        if value is not None:
            result.append(column == value)
    if industry_group:
        result.append(
            Company.industry_id.in_(select(Industry.id).where(Industry.group == industry_group))
        )
    if q:
        result.append(
            Company.name_normalized.contains(normalize_name(q) or q.strip(), autoescape=True)
            | Company.inn.icontains(q.strip(), autoescape=True)
        )
    return result


def list_companies(
    session: Session,
    *,
    region_id=None,
    industry_id=None,
    industry_group=None,
    client_status=None,
    min_revenue=None,
    min_growth=None,
    municipality=None,
    q=None,
    report_year=None,
    limit=50,
    offset=0,
) -> list[CompanyOut]:
    data = financials(report_year)
    statement = (
        select(
            Company,
            data.c.revenue_latest,
            data.c.revenue_year,
            data.c.revenue_yoy,
            data.c.revenue_is_synthetic,
        )
        .outerjoin(data, data.c.company_id == Company.id)
        .where(
            *company_conditions(
                region_id=region_id,
                industry_id=industry_id,
                industry_group=industry_group,
                client_status=client_status,
                municipality=municipality,
                q=q,
            )
        )
    )
    if min_revenue is not None:
        statement = statement.where(data.c.revenue_latest >= min_revenue)
    if min_growth is not None:
        statement = statement.where(data.c.revenue_yoy >= min_growth)
    rows = session.execute(statement.order_by(Company.name, Company.id).limit(limit).offset(offset))
    return [
        CompanyOut.model_validate(company).model_copy(
            update={
                "revenue_latest": revenue,
                "revenue_year": year,
                "revenue_yoy": round(float(growth), 1) if growth is not None else None,
                "revenue_is_synthetic": bool(synthetic),
            }
        )
        for company, revenue, year, growth, synthetic in rows
    ]


def _slices(session, report_year, level):
    data = financials(report_year)
    local = Company.municipality if level == "municipality" else literal(None)
    grouping = [
        Company.region_id,
        Region.name,
        Industry.group,
        Region.center_lon,
        Region.center_lat,
    ]
    if level == "municipality":
        grouping.append(Company.municipality)
    statement = (
        select(
            Company.region_id.label("region_id"),
            Region.name.label("region_name"),
            Industry.group.label("industry_group"),
            local.label("municipality"),
            func.count(Company.id).label("companies_count"),
            func.sum(data.c.revenue_latest).label("revenue_sum"),
            func.count(data.c.revenue_latest).label("revenue_companies"),
            func.count(data.c.revenue_yoy).label("growth_companies"),
            func.sum(case((data.c.revenue_yoy >= 5, 1), else_=0)).label("growing_count"),
            func.sum(case((Company.client_status == "active", 1), else_=0)).label("client_count"),
            func.sum(
                case(
                    (Company.is_synthetic.is_(True) | data.c.revenue_is_synthetic.is_(True), 1),
                    else_=0,
                )
            ).label("synthetic_count"),
            Region.center_lon.label("longitude"),
            Region.center_lat.label("latitude"),
        )
        .select_from(Company)
        .join(Region, Company.region_id == Region.id)
        .join(Industry, Company.industry_id == Industry.id)
        .outerjoin(data, data.c.company_id == Company.id)
        .group_by(*grouping)
        .order_by(Company.region_id, Industry.group, local)
    )
    return session.execute(statement).mappings().all()


def _presence(session, service_type=None):
    statement = select(CustomerPresence).where(CustomerPresence.as_of_date <= date.today())
    if service_type:
        statement = statement.where(CustomerPresence.service_type == service_type)
    latest = {}
    for row in session.scalars(
        statement.order_by(CustomerPresence.as_of_date.desc(), CustomerPresence.id.desc())
    ):
        latest.setdefault((row.region_id, row.municipality, row.service_type), row)
    grouped = {}
    for row in latest.values():
        grouped.setdefault((row.region_id, row.municipality), []).append(row)
    result = {}
    for key, rows in grouped.items():
        if any(r.coverage_percent is None or r.contracts_count is None for r in rows):
            continue
        coverage = sum(float(r.coverage_percent) for r in rows) / len(rows)
        contracts = sum(r.contracts_count for r in rows)
        score = round(min(coverage * 0.7 + min(contracts / 20, 1) * 30, 100), 1)
        result[key] = (score, coverage, any(r.is_synthetic for r in rows))
    return result


def presence_score(
    session: Session, region_id: int, service_type: str | None = None
) -> float | None:
    record = _presence(session, service_type).get((region_id, None))
    return record[0] if record else None


def _activity(session, kind, level):
    if kind == "projects":
        rid, local = InvestmentProject.region_id, InvestmentProject.municipality
        statement = (
            select(rid, Industry.group, func.count(InvestmentProject.id))
            .select_from(InvestmentProject)
            .join(Industry, InvestmentProject.industry_id == Industry.id)
            .where(InvestmentProject.stage.in_(("design", "modernization", "construction")))
        )
    else:
        rid, local = Company.region_id, Company.municipality
        statement = (
            select(rid, Industry.group, func.count(Tender.id))
            .select_from(Tender)
            .join(Company, Tender.customer_company_id == Company.id)
            .join(Industry, Company.industry_id == Industry.id)
            .where(Tender.deadline_date >= date.today(), Tender.status == "published")
        )
    grouping = [rid, Industry.group]
    if level == "municipality":
        statement = statement.add_columns(local)
        grouping.append(local)
    return {
        (r[0], r[3] if level == "municipality" else None, r[1]): r[2]
        for r in session.execute(statement.group_by(*grouping))
    }


def _key(cell):
    return cell["region_id"], cell["municipality"], cell["industry_group"]


def _cells(
    session,
    *,
    level="region",
    report_year=None,
    service_type=None,
    active_projects=None,
    open_tenders=None,
):
    if report_year is None:
        report_year = session.scalar(
            select(func.max(CompanyMetric.period_year)).where(
                CompanyMetric.metric_code == "revenue"
            )
        )
    slices = _slices(session, report_year, level)
    if not slices:
        return [], {}, {}, {}
    projects = _activity(session, "projects", level)
    tenders = _activity(session, "tenders", level)
    if active_projects is not None and level == "region":
        projects = {(rid, None, group): count for (rid, group), count in active_projects.items()}
    if open_tenders is not None and level == "region":
        tenders = {(rid, None, group): count for (rid, group), count in open_tenders.items()}
    presence = _presence(session, service_type)
    revenue_max = max(
        (float(s["revenue_sum"]) for s in slices if s["revenue_sum"] is not None), default=0
    )
    density_max = max(s["companies_count"] for s in slices)
    now = datetime.now(UTC)
    cells = []
    for s in slices:
        key = _key(s)
        growth = s["growing_count"] / s["growth_companies"] if s["growth_companies"] else None
        potential = score_potential(
            PotentialInput(
                revenue_sum=float(s["revenue_sum"] or 0),
                revenue_sum_max=revenue_max,
                growth_share=growth or 0,
                companies_count=s["companies_count"],
                companies_count_max=density_max,
                active_projects=projects.get(key, 0),
                active_projects_max=max(projects.values(), default=0),
                open_tenders=tenders.get(key, 0),
                open_tenders_max=max(tenders.values(), default=0),
            )
        )
        covered = presence.get((s["region_id"], s["municipality"]))
        synthetic = bool(s["synthetic_count"]) or bool(covered and covered[2])
        complete = (
            s["revenue_companies"] == s["companies_count"]
            and s["growth_companies"] == s["companies_count"]
            and covered is not None
        )
        cells.append(
            HeatCellOut(
                region_id=s["region_id"],
                region_name=s["region_name"],
                industry_group=s["industry_group"],
                municipality=s["municipality"],
                geography_level=level,
                companies_count=s["companies_count"],
                revenue_sum=s["revenue_sum"],
                revenue_year=report_year,
                revenue_companies=s["revenue_companies"],
                growth_companies=s["growth_companies"],
                growth_share=round(growth, 3) if growth is not None else None,
                potential_score=potential.score,
                presence_score=covered[0] if covered else None,
                longitude=s["longitude"] if level == "region" else None,
                latitude=s["latitude"] if level == "region" else None,
                factors=potential.factors,
                calculated_at=now,
                model_version=MODEL_VERSION,
                is_synthetic=synthetic,
                data_quality="sufficient" if complete and not synthetic else "limited",
                confidence="medium" if complete else "low",
            )
        )
    return cells, {_key(s): s for s in slices}, projects, presence


def _selected(cell, region_id, industry_group, municipality):
    return (
        (region_id is None or cell.region_id == region_id)
        and (industry_group is None or cell.industry_group == industry_group)
        and (municipality is None or cell.municipality == municipality)
    )


def heatmap(
    session: Session,
    *,
    region_id=None,
    industry_group=None,
    active_projects=None,
    open_tenders=None,
    municipality=None,
    level="region",
    report_year=None,
    service_type=None,
    _bypass_cache=False,
):
    if not _bypass_cache and report_year is None and service_type is None:
        from modules.readmodels.service import get_snapshot

        cached = get_snapshot(session, "radar", "municipality" if municipality else level)
        if cached is not None:
            return [
                c
                for row in cached
                if _selected(
                    c := HeatCellOut.model_validate(row), region_id, industry_group, municipality
                )
            ]
    cells, _, _, _ = _cells(
        session,
        level="municipality" if municipality else level,
        report_year=report_year,
        service_type=service_type,
        active_projects=active_projects,
        open_tenders=open_tenders,
    )
    return [c for c in cells if _selected(c, region_id, industry_group, municipality)]


def white_spaces(
    session: Session,
    *,
    region_id=None,
    industry_group=None,
    active_projects=None,
    open_tenders=None,
    municipality=None,
    level="region",
    report_year=None,
    service_type=None,
    _bypass_cache=False,
):
    if not _bypass_cache and report_year is None and service_type is None:
        from modules.readmodels.service import get_snapshot

        cached = get_snapshot(session, "white", "municipality" if municipality else level)
        if cached is not None:
            return [
                c
                for row in cached
                if _selected(
                    c := WhiteSpaceOut.model_validate(row), region_id, industry_group, municipality
                )
            ]
    actual_level = "municipality" if municipality else level
    cells, slices, projects, presence = _cells(
        session,
        level=actual_level,
        report_year=report_year,
        service_type=service_type,
        active_projects=active_projects,
        open_tenders=open_tenders,
    )
    eligible = [
        c
        for c in cells
        if c.presence_score is not None and c.revenue_companies > 0 and c.potential_score > 0
    ]
    if not eligible:
        return []
    p75 = quartile_cut([c.potential_score for c in eligible], 0.75)
    p25 = quartile_cut([c.presence_score for c in eligible], 0.25)
    result = []
    for cell in eligible:
        if not _selected(cell, region_id, industry_group, municipality):
            continue
        if not is_white_space(cell.potential_score, cell.presence_score, p75, p25):
            continue
        key = cell.region_id, cell.municipality, cell.industry_group
        s = slices[key]
        explanation = explain_white_space(
            companies_count=s["companies_count"],
            client_count=s["client_count"],
            active_projects=projects.get(key, 0),
            revenue_yoy=None,
            coverage_percent=presence[(cell.region_id, cell.municipality)][1],
        )
        if cell.is_synthetic:
            explanation.append("Расчёт использует синтетические данные — демонстрационный режим")
        result.append(
            WhiteSpaceOut(
                region_id=cell.region_id,
                region_name=cell.region_name,
                industry_group=cell.industry_group,
                municipality=cell.municipality,
                geography_level=actual_level,
                service_type=service_type,
                potential_score=cell.potential_score,
                presence_score=cell.presence_score,
                explanation=explanation,
                calculated_at=cell.calculated_at,
                model_version=MODEL_VERSION,
                confidence=cell.confidence,
                data_quality=cell.data_quality,
                is_synthetic=cell.is_synthetic,
                thresholds={"potential_p75": p75, "presence_p25": p25},
            )
        )
    return sorted(result, key=lambda c: -c.potential_score)


def derive_client_status(has_presence: bool, has_demand_signal: bool) -> str:
    return "active" if has_presence else "prospect" if has_demand_signal else "unknown"
