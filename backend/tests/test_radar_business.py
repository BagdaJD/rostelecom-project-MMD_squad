"""Regressions for source deduplication, annual cohorts and stable scoring filters."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Company, CompanyMetric, CustomerPresence, Industry, Region, SourceRecord
from ingestion.loader import _source, load_companies
from ingestion.normalize import RawCompany
from modules.radar import service as radar
from modules.radar.metrics import metrics_for_company


def metric(session, company, year, value, *, source="actual", revision="1", fetched=None):
    record = _source(session, source, f"{company.id}-{year}-{revision}", {"revision": revision})
    if fetched:
        record.fetched_at = fetched
    session.add(
        CompanyMetric(
            company_id=company.id,
            metric_code="revenue",
            period_year=year,
            value=value,
            source_id=record.id,
            fetched_at=datetime.now(UTC),
        )
    )
    session.flush()


def company(session, region, industry, name, municipality="Town"):
    row = Company(
        name=name,
        name_normalized=name.lower(),
        region_id=region.id,
        industry_id=industry.id,
        municipality=municipality,
    )
    session.add(row)
    session.flush()
    return row


def test_revenue_deduplicates_sources_preserves_zero_and_requires_adjacent_year(business_db):
    session, _ = business_db
    region, industry = (
        Region(code="R", name="Region"),
        Industry(code="I", name="Industry", group="G"),
    )
    session.add_all([region, industry])
    session.flush()
    growing = company(session, region, industry, "Z growing")
    zero = company(session, region, industry, "A zero")
    gap = company(session, region, industry, "B gap")
    missing = company(session, region, industry, "C missing")
    now = datetime.now(UTC)
    metric(session, growing, 2023, 100)
    metric(session, growing, 2024, 110, fetched=now - timedelta(days=2))
    metric(session, growing, 2024, 120, revision="2", fetched=now - timedelta(days=1))
    metric(session, growing, 2024, 99999, source="demo", fetched=now)
    metric(session, zero, 2023, 100)
    metric(session, zero, 2024, 0)
    metric(session, gap, 2022, 50)
    metric(session, gap, 2024, 100)
    metric(session, missing, 2023, 100)
    metric(session, missing, 2024, None)
    selected = radar.list_companies(session, min_revenue=110, limit=1)
    assert len(selected) == 1 and selected[0].id == growing.id
    assert selected[0].revenue_latest == Decimal("120")
    assert selected[0].revenue_yoy == pytest.approx(20)
    assert not selected[0].revenue_is_synthetic
    rows = {row.id: row for row in radar.list_companies(session)}
    assert rows[zero.id].revenue_latest == 0 and rows[zero.id].revenue_yoy == -100
    assert rows[gap.id].revenue_yoy is None
    assert rows[missing.id].revenue_latest is None and rows[missing.id].revenue_yoy is None
    assert len(metrics_for_company(session, growing.id)) == 2
    cell = radar.heatmap(session)[0]
    assert cell.companies_count == 4 and cell.revenue_sum == Decimal("220")
    assert cell.revenue_year == 2024 and cell.revenue_companies == 3 and cell.growth_companies == 2
    assert cell.growth_share == 0.5 and cell.presence_score is None
    assert radar.heatmap(session, report_year=2023)[0].revenue_sum == Decimal("300")
    assert radar.white_spaces(session) == []


def test_observed_company_with_demo_revenue_marks_financials_and_heatmap(business_db):
    session, _ = business_db
    region, industry = (
        Region(code="R", name="Region"),
        Industry(code="I", name="Industry", group="G"),
    )
    session.add_all([region, industry])
    session.flush()
    row = company(session, region, industry, "Observed")
    metric(session, row, 2024, 100, source="demo")
    out = radar.list_companies(session)[0]
    assert not out.is_synthetic and out.revenue_is_synthetic
    assert radar.heatmap(session)[0].is_synthetic
    assert metrics_for_company(session, row.id)[0]["is_synthetic"]


def test_filtered_scores_equal_global_scores_and_presence_uses_latest_snapshot(business_db):
    session, _ = business_db
    industry = Industry(code="I", name="Industry", group="G")
    regions = [Region(code=f"R{i}", name=f"Region {i}") for i in range(3)]
    session.add_all([industry, *regions])
    session.flush()
    for i, (region, revenue, coverage) in enumerate(
        zip(regions, [1000, 100, 10], [0, 80, 100], strict=True)
    ):
        row = company(session, region, industry, f"Company {i}")
        metric(session, row, 2023, revenue / (2 if i == 0 else 1))
        metric(session, row, 2024, revenue)
        session.add(
            CustomerPresence(
                region_id=region.id,
                service_type="internet",
                coverage_percent=coverage,
                contracts_count=0,
                as_of_date=date.today(),
                is_synthetic=False,
            )
        )

    for delta in (-100, 100):
        session.add(
            CustomerPresence(
                region_id=regions[0].id,
                service_type="internet",
                coverage_percent=100,
                contracts_count=100,
                as_of_date=date.today() + timedelta(days=delta),
                is_synthetic=False,
            )
        )
    session.flush()
    all_cells = radar.heatmap(session)
    high = next(c for c in all_cells if c.region_id == regions[0].id)
    assert high.presence_score == 0
    filtered = radar.heatmap(session, region_id=regions[0].id)[0]
    assert filtered.potential_score == high.potential_score
    whites = radar.white_spaces(session)
    assert [w.region_id for w in whites] == [regions[0].id]
    assert whites[0].potential_score == high.potential_score
    assert whites[0].presence_score == high.presence_score
    assert (
        radar.white_spaces(session, region_id=regions[0].id)[0].thresholds == whites[0].thresholds
    )
    municipal = radar.heatmap(session, level="municipality")
    assert sum(c.companies_count for c in municipal) == 3
    assert all(c.municipality == "Town" and c.presence_score is None for c in municipal)
    assert radar.white_spaces(session, level="municipality") == []


def test_demo_import_cannot_overwrite_observed_company(business_db):
    session, _ = business_db
    observed = RawCompany(
        source="actual",
        external_id="a",
        name="Observed",
        inn="7710137066",
        employee_count=0,
        municipality="Verified town",
    )
    demo = RawCompany(
        source="demo", external_id="d", name="Synthetic", inn=observed.inn, employee_count=999
    )
    load_companies(session, [observed], {}, {})
    session.flush()
    load_companies(session, [demo], {}, {})
    session.flush()
    row = session.scalar(select(Company))
    assert row.name == "Observed" and row.employee_count == 0 and not row.is_synthetic
    assert row.municipality == "Verified town"
    assert session.get(SourceRecord, row.source_id).source == "actual"
