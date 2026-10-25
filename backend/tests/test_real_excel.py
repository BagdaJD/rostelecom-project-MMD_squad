"""Фактические локальные данные — без добавления персональных сведений в репозиторий."""

import os
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import (
    Company,
    CompanyMatch,
    InvestmentProject,
    ProjectNeed,
    ScoringSnapshot,
    SourceRecord,
)
from ingestion.persistence import import_result
from ingestion.pipeline import run_pipeline
from tests.test_pipeline_storage import sql_session as sql_session


def test_organizer_excel_full_batch_and_sql_idempotency(sql_session):
    path = os.environ.get("MMD_EXCEL_PATH")
    if not path or not Path(path).is_file():
        pytest.skip("MMD_EXCEL_PATH не задан; исходный Excel не распространяется с кодом")
    data = run_pipeline(path, as_of=date(2026, 10, 24))
    quality = data["quality"]
    assert quality["source_companies"] == quality["companies"] == 759
    assert quality["source_projects"] == quality["projects"] == 63
    assert quality["original_unchanged"] and quality["valid_inn_percent"] == 100
    import_result(sql_session, data)
    tables = [Company, CompanyMatch, InvestmentProject, ProjectNeed, SourceRecord, ScoringSnapshot]
    counts = [sql_session.scalar(select(func.count(t.id))) for t in tables]
    import_result(sql_session, data)
    assert counts == [sql_session.scalar(select(func.count(t.id))) for t in tables]
    assert sql_session.scalar(select(func.count(Company.id))) == 759
    assert sql_session.scalar(select(func.count(InvestmentProject.id))) == 63
    assert all(p["recommendations"] for p in data["projects"])
    assert all(
        c["scoring"]["score"] is None or 0 <= c["scoring"]["score"] <= 100
        for c in data["companies"]
    )
