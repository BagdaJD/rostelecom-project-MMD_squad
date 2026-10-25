"""One source per metric/year, selected by source nature and retrieval time, never value."""

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.models import CompanyMetric, SourceRecord


def canonical_metrics():
    synthetic = case(
        (
            or_(
                SourceRecord.source == "demo",
                SourceRecord.source.startswith("synthetic"),
                SourceRecord.raw_payload["is_synthetic"].as_boolean().is_(True),
            ),
            True,
        ),
        else_=False,
    )
    priority = case((synthetic, 0), else_=1)
    ranked = (
        select(
            *CompanyMetric.__table__.c,
            synthetic.label("is_synthetic"),
            func.row_number()
            .over(
                partition_by=(
                    CompanyMetric.company_id,
                    CompanyMetric.metric_code,
                    CompanyMetric.period_year,
                ),
                order_by=(
                    priority.desc(),
                    SourceRecord.fetched_at.desc(),
                    CompanyMetric.fetched_at.desc(),
                    CompanyMetric.id.desc(),
                ),
            )
            .label("source_rank"),
        )
        .join(SourceRecord, CompanyMetric.source_id == SourceRecord.id)
        .subquery()
    )
    return (
        select(*[ranked.c[col.name] for col in CompanyMetric.__table__.c], ranked.c.is_synthetic)
        .where(ranked.c.source_rank == 1)
        .subquery()
    )


def financials(report_year: int | None = None):
    annual = canonical_metrics()
    revenues = select(
        *annual.c,
        func.row_number()
        .over(partition_by=annual.c.company_id, order_by=annual.c.period_year.desc())
        .label("year_rank"),
    ).where(annual.c.metric_code == "revenue")
    if report_year is not None:
        revenues = revenues.where(annual.c.period_year == report_year)
    current = revenues.subquery()
    previous = annual.alias("previous_revenue")
    yoy = case(
        (
            and_(current.c.value.is_not(None), previous.c.value > 0),
            (current.c.value - previous.c.value) * 100 / previous.c.value,
        ),
        else_=None,
    )
    return (
        select(
            current.c.company_id,
            current.c.period_year.label("revenue_year"),
            current.c.value.label("revenue_latest"),
            yoy.label("revenue_yoy"),
            or_(current.c.is_synthetic, and_(yoy.is_not(None), previous.c.is_synthetic)).label(
                "revenue_is_synthetic"
            ),
        )
        .outerjoin(
            previous,
            and_(
                previous.c.company_id == current.c.company_id,
                previous.c.metric_code == "revenue",
                previous.c.period_year == current.c.period_year - 1,
            ),
        )
        .where(current.c.year_rank == 1)
        .subquery()
    )


def metrics_for_company(session: Session, company_id: int):
    metrics = canonical_metrics()
    return (
        session.execute(
            select(metrics)
            .where(metrics.c.company_id == company_id)
            .order_by(metrics.c.metric_code, metrics.c.period_year)
        )
        .mappings()
        .all()
    )
