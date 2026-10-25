"""SQL/API проверки на SQLite — отдельно от настоящих PostgreSQL/PostGIS тестов."""

import os
from datetime import UTC, date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from geoalchemy2 import Geometry
from sqlalchemy import MetaData, Text, create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints.investments import router as investments_router
from app.api.v1.endpoints.radar import router as radar_router
from app.core.deps import get_current_user
from app.db.session import get_session
from app.models import (
    Base,
    Company,
    CompanyMatch,
    CompanyMetric,
    InvestmentProject,
    ProjectNeed,
    Region,
    ScoringSnapshot,
    SourceRecord,
)
from ingestion.persistence import import_result, saved_company_score
from ingestion.pipeline import run_pipeline
from modules.radar.service import _slices, heatmap, latest_revenue, revenue_yoy
from tests.test_pipeline_normalization import tiny_excel as tiny_excel


@pytest.fixture
def sql_session():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def sqlite_geometry_null_only(connection, _):
        # В тестовых данных нет геометрии; PostGIS этим тестом не проверяется.
        for name in ("ST_AsEWKB", "AsEWKB", "ST_GeomFromEWKT", "GeomFromEWKT"):
            connection.create_function(name, 1, lambda value: value)

    metadata = MetaData()
    for original in Base.metadata.sorted_tables:
        table = original.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, Geometry):
                column.type = Text()
    metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_excel_to_db_needs_scores_api_and_repeat(tiny_excel, sql_session):
    data = run_pipeline(tiny_excel, as_of=date(2026, 10, 24))
    first = import_result(sql_session, data)
    sql_session.commit()
    tables = [Company, CompanyMatch, InvestmentProject, ProjectNeed, SourceRecord, ScoringSnapshot]
    counts = [sql_session.scalar(select(func.count(t.id))) for t in tables]
    second = import_result(sql_session, data)
    sql_session.commit()
    assert counts == [sql_session.scalar(select(func.count(t.id))) for t in tables]
    assert first["created_companies"] == first["created_projects"] == 1
    assert second["created_companies"] == second["created_projects"] == 0
    project = sql_session.scalar(select(InvestmentProject))
    assert project.initiator_company_id is None  # Совпадение по названию не подтверждено.
    assert project.estimated_budget == Decimal("136000000")
    assert project.stage == "unknown" and project.planned_start is None
    company = sql_session.scalar(select(Company))
    assert company.coordinates is None
    assert saved_company_score(sql_session, company.id)["score"] is not None
    app = FastAPI()
    app.include_router(investments_router)
    app.include_router(radar_router)
    app.dependency_overrides[get_session] = lambda: sql_session
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="analyst")
    with TestClient(app) as client:
        response = client.get(f"/investments/{project.id}/needs")
        assert response.status_code == 200
        needs = response.json()
        assert needs and all(n["evidence_type"] == "inferred" for n in needs)
        assert all(n["probability"] is None and n["evidence"] is None for n in needs)
        response = client.get(f"/companies/{company.id}/score")
        assert response.status_code == 200 and response.json()["scoring_mode"] == "heuristic"
        response = client.get("/companies")
        assert response.status_code == 200 and response.json()[0]["score"] is not None
        heat = client.get("/radar/heatmap").json()[0]
        assert heat["presence_score"] is None
        assert heat["potential_score"] == data["territories"][0]["potential_score"]
        assert client.get("/radar/white-spaces").json() == []


def test_radar_counts_companies_once_and_uses_last_metric(tiny_excel, sql_session):
    import_result(sql_session, run_pipeline(tiny_excel, as_of=date(2026, 10, 24)))
    company = sql_session.scalar(select(Company))
    source = sql_session.scalar(select(SourceRecord))
    from datetime import datetime

    for year, value in ((2023, 100), (2024, 150), (2024, 120)):
        sql_session.add(
            CompanyMetric(
                company_id=company.id,
                metric_code="revenue",
                period_year=year,
                value=value,
                source_id=source.id,
                fetched_at=datetime.now(UTC),
            )
        )
        sql_session.flush()
        # У одного источника значение за год уникально, имитируем второй источник.
        source = SourceRecord(
            source="test", external_id=str(value), raw_payload={}, processing_status="processed"
        )
        sql_session.add(source)
        sql_session.flush()
    slices = _slices(sql_session, None, None)
    assert slices[0].companies_count == 1 and slices[0].revenue_sum == 120
    assert latest_revenue(sql_session, [company.id])[company.id][1] == 120
    assert revenue_yoy(sql_session, [company.id])[company.id] == 20
    assert heatmap(sql_session)[0].revenue_sum == 120


def test_revenue_gap_is_not_annual_growth(tiny_excel, sql_session):
    import_result(sql_session, run_pipeline(tiny_excel, as_of=date(2026, 10, 24)))
    company = sql_session.scalar(select(Company))
    source = sql_session.scalar(select(SourceRecord))
    from datetime import datetime

    for year, value in ((2023, 100), (2025, 200)):
        sql_session.add(
            CompanyMetric(
                company_id=company.id,
                metric_code="revenue",
                period_year=year,
                value=value,
                source_id=source.id,
                fetched_at=datetime.now(UTC),
            )
        )
    sql_session.flush()
    assert revenue_yoy(sql_session, [company.id]) == {}
    assert heatmap(sql_session)[0].growth_share is None


def test_same_names_with_different_ids_are_separate_and_repeatable(sql_session):
    from ingestion.loader import load_companies
    from ingestion.normalize import RawCompany

    region = Region(code="61", name="Тестовый регион")
    sql_session.add(region)
    sql_session.flush()
    records = [
        RawCompany(
            source="test",
            external_id=str(i),
            name="ООО Тестовая компания",
            inn=inn,
            region_code="61",
        )
        for i, inn in enumerate(("1234567894", "012345678943"))
    ]
    load_companies(sql_session, records + records, {}, {"61": region.id})
    assert sql_session.scalar(select(func.count(Company.id))) == 2
    assert sql_session.scalar(select(func.count(CompanyMatch.id))) == 2
    load_companies(sql_session, records, {}, {"61": region.id})
    assert sql_session.scalar(select(func.count(Company.id))) == 2
    assert sql_session.scalar(select(func.count(CompanyMatch.id))) == 2


def test_insufficient_score_persists_as_null(tiny_excel, sql_session):
    from ml.scoring import score_company

    data = run_pipeline(tiny_excel, as_of=date(2026, 10, 24))
    data["companies"][0]["scoring"] = score_company({}, as_of=date(2026, 10, 24))
    import_result(sql_session, data)
    company = sql_session.scalar(select(Company))
    result = saved_company_score(sql_session, company.id)
    assert result["score"] is None and result["data_quality"] == "insufficient"


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("MMD_TEST_DATABASE_URL"), reason="Нужна явная выделенная PostgreSQL"
)
def test_postgresql_pipeline_in_rollback_transaction(tiny_excel):
    from tests.postgres_support import isolated_session

    with isolated_session() as session:
        try:
            data = run_pipeline(tiny_excel, as_of=date(2026, 10, 24))
            import_result(session, data)
            before = session.scalar(select(func.count(Company.id)))
            import_result(session, data)
            assert session.scalar(select(func.count(Company.id))) == before
            assert session.scalar(select(func.count(ProjectNeed.id))) > 0
        finally:
            session.rollback()
