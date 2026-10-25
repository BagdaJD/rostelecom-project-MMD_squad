"""Настоящий PostgreSQL/PostGIS: явный owned marker, реальные данные, rollback."""

import json
import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from geoalchemy2 import WKTElement
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.api.v1.endpoints.investments import router as investments_router
from app.api.v1.endpoints.radar import router as radar_router
from app.core.deps import get_current_user
from app.db.session import get_session
from app.models import (
    Company,
    CompanyMatch,
    CompanyMetric,
    InvestmentProject,
    ProjectNeed,
    ScoringSnapshot,
    SourceRecord,
)
from ingestion.normalize import RawCompany
from ingestion.persistence import import_result
from ingestion.pipeline import analyze, run_pipeline
from ingestion.sources.excel_source import read_excel
from tests.postgres_support import isolated_session
from tests.postgres_support import test_engine as owned_engine
from tests.test_pipeline_normalization import tiny_excel as tiny_excel

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("MMD_TEST_DATABASE_URL"),
        reason="Не задана отдельная marker-защищённая PostgreSQL",
    ),
]


@pytest.fixture
def pg_session():
    with isolated_session() as session:
        yield session


def _alembic(connection):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.attributes["connection"] = connection
    return config


def test_migration_roundtrip_preserves_existing_rows(tiny_excel, pg_session):
    data = run_pipeline(tiny_excel, as_of=date(2026, 10, 24))
    import_result(pg_session, data)
    connection = pg_session.connection()
    before = connection.execute(text("SELECT count(*),sum(score) FROM scoring_snapshot")).one()
    count_before = connection.execute(text("SELECT count(*) FROM project_need")).scalar_one()
    command.downgrade(_alembic(connection), "20261025_0005")
    assert (
        connection.execute(text("SELECT count(*) FROM project_need")).scalar_one() == count_before
    )
    assert (
        connection.execute(text("SELECT count(*),sum(score) FROM scoring_snapshot")).one() == before
    )
    command.upgrade(_alembic(connection), "head")
    assert (
        connection.execute(
            text("SELECT count(*) FROM project_need WHERE details_json IS NULL")
        ).scalar_one()
        == count_before
    )
    connection.execute(
        text(
            "INSERT INTO scoring_snapshot"
            "(subject_type,subject_id,score,factors_json,scoring_mode,model_version) "
            "VALUES ('company',-1,NULL,'[]','heuristic','migration-test')"
        )
    )
    assert (
        connection.execute(
            text("SELECT count(*) FROM scoring_snapshot WHERE score IS NULL")
        ).scalar_one()
        == 1
    )
    # Нельзя откатить nullable при наличии отказа от скоринга; данные не удаляются.
    with pytest.raises(RuntimeError, match="NOT NULL"):
        command.downgrade(_alembic(connection), "20261025_0005")


def test_postgis_geometry_nulls_foreign_keys_and_savepoints(tiny_excel, pg_session):
    versions = pg_session.execute(text("SELECT postgis_version(), current_database()")).one()
    assert versions[0] and versions[1].startswith("mmd_ml_test_")
    assert (
        pg_session.execute(
            text("SELECT count(*) FROM pg_indexes WHERE indexname='ix_company_ogrn'")
        ).scalar_one()
        == 1
    )
    assert (
        pg_session.execute(
            text(
                "SELECT count(*) FROM pg_indexes "
                "WHERE indexname='ix_company_match_source_record_id'"
            )
        ).scalar_one()
        == 1
    )
    import_result(pg_session, run_pipeline(tiny_excel, as_of=date(2026, 10, 24)))
    assert (
        pg_session.scalar(select(func.count(Company.id)).where(Company.coordinates.is_not(None)))
        == 0
    )
    with pg_session.begin_nested():
        point = Company(
            name="Тест геометрии",
            name_normalized="тест геометрии",
            coordinates=WKTElement("POINT(1 2)", srid=4326),
        )
        pg_session.add(point)
        pg_session.flush()
        row = pg_session.execute(
            text(
                "SELECT ST_X(coordinates),ST_Y(coordinates),ST_SRID(coordinates) "
                "FROM company WHERE id=:id"
            ),
            {"id": point.id},
        ).one()
        assert tuple(row) == (1, 2, 4326)
    count = pg_session.scalar(select(func.count(SourceRecord.id)))
    savepoint = pg_session.begin_nested()
    pg_session.add(
        SourceRecord(source="rollback-test", processing_status="processed", raw_payload={})
    )
    pg_session.flush()
    savepoint.rollback()
    assert pg_session.scalar(select(func.count(SourceRecord.id))) == count
    with pytest.raises(IntegrityError), pg_session.begin_nested():
        pg_session.add(
            ProjectNeed(project_id=-9999, need_category="connectivity", model_version="fk-test")
        )
        pg_session.flush()
    assert pg_session.scalar(select(func.count(Company.id))) > 0


def test_real_excel_optional_fns_to_postgresql_and_all_api(pg_session):
    excel = os.environ.get("MMD_EXCEL_PATH")
    if not excel:
        pytest.skip("Нужен исходный Excel через MMD_EXCEL_PATH")
    original = read_excel(excel)
    records = original.companies
    fns_path = os.environ.get("MMD_FNS_JSONL")
    fns_count = 0
    if fns_path:
        with Path(fns_path).open(encoding="utf-8") as stream:
            for line in stream:
                records.append(RawCompany(**json.loads(line)))
                fns_count += 1
                if fns_count == 500:
                    break
    data = analyze(records, original.projects, as_of=date(2026, 10, 24))
    stats = import_result(pg_session, data)
    tables = (
        Company,
        CompanyMatch,
        CompanyMetric,
        InvestmentProject,
        ProjectNeed,
        SourceRecord,
        ScoringSnapshot,
    )
    before = [pg_session.scalar(select(func.count(t.id))) for t in tables]
    import_result(pg_session, data)
    assert before == [pg_session.scalar(select(func.count(t.id))) for t in tables]
    assert stats["processed_projects"] == 63
    assert before[0] == len(data["companies"])
    assert pg_session.scalar(select(func.count(ProjectNeed.id))) >= 63
    assert pg_session.scalar(
        select(func.count(ScoringSnapshot.id)).where(ScoringSnapshot.subject_type == "company")
    ) == len(data["companies"])
    project = pg_session.scalar(select(InvestmentProject).order_by(InvestmentProject.id))
    company = pg_session.scalar(select(Company).order_by(Company.id))
    app = FastAPI()
    app.include_router(investments_router, prefix="/api/v1")
    app.include_router(radar_router, prefix="/api/v1")
    app.dependency_overrides[get_session] = lambda: pg_session
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="analyst")
    with TestClient(app) as client:
        response = client.get(f"/api/v1/investments/{project.id}/needs")
        assert response.status_code == 200
        needs = response.json()
        assert needs and all(n["probability"] is None for n in needs)
        assert all(n["evidence_type"] in ("explicit", "inferred", None) for n in needs)
        assert all(n["evidence"] is None for n in needs if n["evidence_type"] == "inferred")
        response = client.get("/api/v1/companies?limit=500")
        assert response.status_code == 200 and len(response.json()) == min(
            len(data["companies"]), 500
        )
        assert all(c["revenue_latest"] is None for c in response.json())
        response = client.get(f"/api/v1/companies/{company.id}/score")
        assert response.status_code == 200
        score = response.json()
        assert score["scoring_mode"] == "heuristic" and score["feature_coverage"] <= 1
        stored = pg_session.scalar(
            select(ScoringSnapshot).where(
                ScoringSnapshot.subject_type == "company", ScoringSnapshot.subject_id == company.id
            )
        )
        assert score["score"] == stored.score
        response = client.get("/api/v1/radar/heatmap")
        assert response.status_code == 200 and response.json()
        assert all(
            c["presence_score"] is None and c["growth_share"] is None for c in response.json()
        )
        assert all(c["presence_status"] == "insufficient_presence_data" for c in response.json())
        assert client.get("/api/v1/radar/white-spaces").json() == []


def test_connection_guard_rejects_unmarked_database(monkeypatch):
    monkeypatch.setenv("MMD_TEST_DATABASE_URL", "postgresql+psycopg://local@localhost/production")
    monkeypatch.setenv("MMD_TEST_DATABASE_TOKEN", "test")
    with pytest.raises(RuntimeError, match="выделенной"):
        owned_engine()


def test_revenue_lookup_above_postgresql_parameter_limit(pg_session):
    from datetime import UTC, datetime

    from modules.radar.service import latest_revenue

    company = Company(name="Тест лимита параметров", name_normalized="тест лимита параметров")
    source = SourceRecord(
        source="parameter-limit-test", processing_status="processed", raw_payload={}
    )
    pg_session.add_all([company, source])
    pg_session.flush()
    pg_session.add(
        CompanyMetric(
            company_id=company.id,
            metric_code="revenue",
            period_year=2025,
            value=100,
            source_id=source.id,
            fetched_at=datetime.now(UTC),
        )
    )
    pg_session.flush()
    # Старая реализация воспроизводимо падала на 70000 параметров, даже при пустой таблице.
    result = latest_revenue(pg_session, [company.id, *range(-70000, 0)])
    assert len(result) == 1 and result[company.id][1] == 100


def test_batched_loader_matches_legacy_across_boundaries_and_repeat(pg_session):
    from dataclasses import replace
    from datetime import UTC, datetime
    from itertools import batched

    from ingestion.batch_loader import load_company_batch
    from ingestion.loader import load_companies

    first = RawCompany(
        source="batch-test",
        external_id="one",
        name="Synthetic first",
        inn="1234567894",
        ogrn="1027700000008",
        employee_count=None,
        fetched_at=datetime(2026, 10, 25, tzinfo=UTC),
        revenue={2024: 100, 2025: 120},
    )
    records = [
        first,
        replace(
            first,
            source="batch-second",
            external_id="two",
            employee_count=12,
            client_status="active",
            revenue={2025: 125},
        ),
        replace(
            first,
            external_id="fallback-a",
            name="Synthetic fallback",
            inn=None,
            ogrn=None,
            revenue={},
        ),
        replace(
            first,
            external_id="fallback-b",
            name="Synthetic fallback",
            inn=None,
            ogrn=None,
            revenue={},
        ),
        first,
    ]

    def capture():
        companies = {
            c.id: (c.inn, c.name_normalized, c.employee_count, c.client_status)
            for c in pg_session.scalars(select(Company))
        }
        sources = {
            s.id: (s.source, s.payload_hash) for s in pg_session.scalars(select(SourceRecord))
        }
        links = [
            (companies[m.company_id], sources[m.source_record_id], m.match_method)
            for m in pg_session.scalars(select(CompanyMatch))
        ]
        metrics = [
            (companies[m.company_id], sources[m.source_id], m.period_year, m.value)
            for m in pg_session.scalars(select(CompanyMetric))
        ]
        return (
            sorted(companies.values(), key=repr),
            sorted(links, key=repr),
            sorted(metrics, key=repr),
        )

    with pg_session.begin_nested() as savepoint:
        load_companies(pg_session, records, {}, {})
        expected = capture()
        assert len(expected[0]) == 3  # Two name-only objects remain separate.
        savepoint.rollback()
    pg_session.expire_all()
    created = 0
    for batch in batched(records, 2):
        _, _, stats = load_company_batch(pg_session, batch, {}, {})
        created += stats.companies
    assert created == 3 and capture() == expected
    for batch in batched(records, 2):
        _, _, stats = load_company_batch(pg_session, batch, {}, {})
        assert stats.companies == 0
    assert capture() == expected


@pytest.mark.parametrize("batch_size", [1, 2])
def test_batched_loader_preserves_identifier_conflict_guard(pg_session, batch_size):
    from dataclasses import replace
    from itertools import batched

    from ingestion.batch_loader import load_company_batch

    record = RawCompany(
        source="batch-conflict",
        external_id="a",
        name="Synthetic conflict",
        inn="1234567894",
        ogrn="1027700000008",
    )
    stem = "102770000001"
    conflict = replace(record, external_id="b", ogrn=stem + str(int(stem) % 11 % 10))
    with pytest.raises(ValueError, match="Конфликт"):
        for batch in batched([record, conflict], batch_size):
            load_company_batch(pg_session, batch, {}, {})
