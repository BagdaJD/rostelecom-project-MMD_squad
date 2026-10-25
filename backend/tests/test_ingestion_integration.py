"""Интеграционные тесты загрузки: требуют PostgreSQL/PostGIS.

Без доступной БД тесты помечаются skip, а не падают — так `pytest -q` работает и на машине
разработчика без поднятого стека. С запущенным `make up` они проверяют главное требование
критерия «качество данных»: повторный импорт не создаёт неконтролируемых дублей.

Запуск: cd backend && alembic upgrade head && pytest -q -m integration
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import Company, CompanyMetric, InvestmentProject, SourceRecord
from ingestion.loader import load_bundle, read_bundle
from tests.postgres_support import isolated_session

BUNDLE = Path(__file__).resolve().parents[2] / "data" / "seed" / "demo_bundle.json"


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("MMD_TEST_DATABASE_URL"),
        reason="нужна явно выделенная PostgreSQL/PostGIS с marker",
    ),
]


@pytest.fixture(scope="module")
def bundle() -> dict:
    assert BUNDLE.exists(), f"нет демо-набора: {BUNDLE}"
    return read_bundle(BUNDLE)


def test_bundle_loads_and_is_idempotent(bundle: dict) -> None:
    with isolated_session() as session:
        first = load_bundle(session, bundle)
        session.commit()
        companies_after_first = session.scalar(select(func.count(Company.id)))

        second = load_bundle(session, bundle)
        session.commit()
        companies_after_second = session.scalar(select(func.count(Company.id)))

    assert companies_after_first and companies_after_first > 0
    assert companies_after_second == companies_after_first
    assert second.companies == 0, "повторный импорт не должен создавать компании"
    assert second.metrics == 0, "повторный импорт не должен создавать метрики"
    assert first.companies > 0


def test_every_fact_has_source_and_date(bundle: dict) -> None:
    """Требование «у каждой записи есть источник и дата» проверяется данными, а не словами."""
    with isolated_session() as session:
        load_bundle(session, bundle)
        session.commit()

        metrics_without_source = session.scalar(
            select(func.count(CompanyMetric.id)).where(CompanyMetric.source_id.is_(None))
        )
        assert metrics_without_source == 0

        stale = session.scalar(
            select(func.count(SourceRecord.id)).where(SourceRecord.fetched_at.is_(None))
        )
        assert stale == 0

        sourceless_projects = session.scalar(
            select(func.count(InvestmentProject.id)).where(InvestmentProject.source_id.is_(None))
        )
        assert sourceless_projects == 0


def test_missing_values_are_not_replaced_with_zero(bundle: dict) -> None:
    with isolated_session() as session:
        load_bundle(session, bundle)
        session.commit()
        negative = session.scalar(
            select(func.count(CompanyMetric.id)).where(CompanyMetric.value < 0)
        )
    assert negative == 0, "отрицательные значения исключаются, известный ноль сохраняется"


@pytest.mark.skipif(os.environ.get("REQUIRE_TENDERS") == "0", reason="отключено явно")
def test_tender_links_record_their_method(bundle: dict) -> None:
    from app.models import ProjectTender

    with isolated_session() as session:
        load_bundle(session, bundle)
        session.commit()
        rows = session.execute(select(ProjectTender.link_method, ProjectTender.confidence)).all()
    for method, confidence in rows:
        assert method in ("external_ref", "inn_keyword", "manual")
        assert 0 <= float(confidence) <= 1
