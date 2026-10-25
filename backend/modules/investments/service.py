"""Инвестиционный навигатор: проекты, таймлайн, потребности, подписки (модуль investments)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    Industry,
    InvestmentEvent,
    InvestmentProject,
    ProjectNeed,
    ProjectTender,
    Tender,
)
from app.schemas import ProjectOut, TimelinePointOut
from ml.needs import classify_need

STAGES = ("design", "modernization", "construction", "launch", "completed", "unknown")


def project_view(project: InvestmentProject) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        title=project.title,
        stage=project.stage,
        planned_start=project.planned_start if project.start_precision == "day" else None,
        estimated_budget=project.estimated_budget,
        region_id=project.region_id,
        industry_id=project.industry_id,
        initiator_company_id=project.initiator_company_id,
        source_url=project.source_url,
        municipality=project.municipality,
        planned_start_year=project.planned_start.year if project.planned_start else None,
        planned_end_year=project.planned_end.year if project.planned_end else None,
        start_precision=project.start_precision,
        end_precision=project.end_precision,
        stage_method=project.stage_method,
        is_synthetic=project.is_synthetic,
    )


def list_projects(
    session: Session,
    *,
    stage: str | None = None,
    industry_id: int | None = None,
    region_id: int | None = None,
    initiator_company_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    municipality: str | None = None,
    q: str | None = None,
) -> list[InvestmentProject]:
    stmt = select(InvestmentProject)
    if stage:
        stmt = stmt.where(InvestmentProject.stage == stage)
    if industry_id:
        stmt = stmt.where(InvestmentProject.industry_id == industry_id)
    if region_id:
        stmt = stmt.where(InvestmentProject.region_id == region_id)
    if initiator_company_id:
        stmt = stmt.where(InvestmentProject.initiator_company_id == initiator_company_id)
    if municipality:
        stmt = stmt.where(InvestmentProject.municipality == municipality)
    if q:
        stmt = stmt.where(InvestmentProject.title.icontains(q.strip(), autoescape=True))
    return list(
        session.scalars(
            stmt.order_by(InvestmentProject.planned_start.desc().nullslast(), InvestmentProject.id)
            .limit(limit)
            .offset(offset)
        )
    )


def linked_tenders(session: Session, project_id: int) -> list[Tender]:
    """Связь N:M через project_tender: у проекта связанных закупок много (ТЗ 6.3)."""
    return list(
        session.scalars(
            select(Tender)
            .join(ProjectTender, ProjectTender.tender_id == Tender.id)
            .where(ProjectTender.project_id == project_id)
            .order_by(Tender.deadline_date.desc().nullslast())
        )
    )


def timeline(
    session: Session,
    *,
    region_id: int | None = None,
    industry_id: int | None = None,
    period: str = "month",
    municipality: str | None = None,
    _bypass_cache: bool = False,
) -> list[TimelinePointOut]:
    """Агрегат таймлайна: точка знает проекты, поэтому клик подсвечивает объекты на карте."""
    if period not in ("month", "quarter", "year"):
        period = "month"
    if not _bypass_cache and municipality is None:
        from modules.readmodels.service import get_snapshot

        cached = get_snapshot(session, "timeline", period)
        if cached is not None:
            return [
                TimelinePointOut.model_validate(row)
                for row in cached
                if (region_id is None or row["region_id"] == region_id)
                and (industry_id is None or row["industry_id"] == industry_id)
            ]

    rows = session.execute(
        select(
            InvestmentEvent.event_date,
            InvestmentEvent.region_id,
            InvestmentEvent.industry_id,
            InvestmentEvent.project_id,
            InvestmentEvent.date_precision,
        )
        .join(InvestmentProject, InvestmentEvent.project_id == InvestmentProject.id)
        .where(InvestmentEvent.event_date.is_not(None))
        .where(InvestmentProject.municipality == municipality if municipality else True)
        .order_by(InvestmentEvent.event_date)
    ).all()

    buckets: dict[tuple[str, int | None, int | None, str], list[int | None]] = defaultdict(list)
    for event_date, rid, iid, pid, precision in rows:
        if region_id and rid != region_id:
            continue
        if industry_id and iid != industry_id:
            continue
        actual_period = "year" if precision == "year" or period == "year" else period
        buckets[(_period_label(event_date, actual_period), rid, iid, actual_period)].append(pid)

    return [
        TimelinePointOut(
            period=key[0],
            region_id=key[1],
            industry_id=key[2],
            events_count=len(items),
            project_ids=sorted({p for p in items if p is not None}),
            date_precision=key[3],
        )
        for key, items in sorted(
            buckets.items(),
            key=lambda item: (item[0][0], item[0][1] or 0, item[0][2] or 0, item[0][3]),
        )
    ]


def _period_label(value: date, period: str) -> str:
    if period == "year":
        return str(value.year)
    if period == "quarter":
        return f"{value.year}Q{(value.month - 1) // 3 + 1}"
    return f"{value.year:04d}-{value.month:02d}"


def active_projects_by_slice(session: Session) -> dict[tuple[int, str], int]:
    """Счётчики активных проектов для скоринга: (region_id, industry_group) → количество."""
    rows = session.execute(
        select(
            InvestmentProject.region_id,
            InvestmentProject.industry_id,
            func.count(InvestmentProject.id),
        )
        .where(InvestmentProject.stage.in_(("design", "modernization", "construction")))
        .group_by(InvestmentProject.region_id, InvestmentProject.industry_id)
    ).all()
    group_of = dict(session.execute(select(Industry.id, Industry.group)).all())

    out: dict[tuple[int, str], int] = defaultdict(int)
    for rid, iid, count in rows:
        group = group_of.get(iid)
        if group and rid:
            out[(rid, group)] += count
    return dict(out)


def open_tenders_by_slice(session: Session) -> dict[tuple[int, str], int]:
    """Открытые закупки по срезу (region, industry_group) — признак скоринга."""
    rows = session.execute(
        select(Company.region_id, Industry.group, func.count(Tender.id))
        .join(Tender, Tender.customer_company_id == Company.id)
        .join(Industry, Company.industry_id == Industry.id)
        .where(Tender.deadline_date >= date.today(), Tender.status == "published")
        .group_by(Company.region_id, Industry.group)
    ).all()
    return {(rid, group): count for rid, group, count in rows if rid and group}


def refresh_needs(
    session: Session, project: InvestmentProject, model_version: str
) -> list[ProjectNeed]:
    """Правила возвращают доказательство из описания — требование объяснимости (ТЗ 8.2)."""
    predictions = classify_need(project.title, project.description)
    session.query(ProjectNeed).filter(ProjectNeed.project_id == project.id).delete()
    created = []
    for pred in predictions:
        need = ProjectNeed(
            project_id=project.id,
            need_category=pred.category,
            probability=pred.probability,
            evidence=pred.evidence,
            rule_id=pred.rule_id,
            model_version=model_version,
        )
        session.add(need)
        created.append(need)
    return created


def matches_subscription(subscription_filters: dict, project: InvestmentProject) -> bool:
    """Подписка срабатывает по тем же фильтрам, что и список: поведение предсказуемо."""
    checks = {
        "stage": project.stage,
        "industry_id": project.industry_id,
        "region_id": project.region_id,
    }
    for key, expected in (subscription_filters or {}).items():
        if key not in checks:
            continue
        if expected is None:
            continue
        if checks[key] != expected:
            return False
    return True
