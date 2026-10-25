"""Prepared reads preserve calculations; HTTP never trains a model."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import (
    DomainEvent,
    InvestmentProject,
    MarketEntrySignal,
    ModelArtifact,
    ReadModelSnapshot,
    Region,
    Tender,
)
from ingestion.case_workbook import import_case, read_case
from ingestion.loader import load_bundle, load_companies, load_projects, load_tenders, read_bundle
from ingestion.normalize import RawCompany
from modules.deal_calculator import artifacts
from modules.deal_calculator import service as calculator
from modules.deal_calculator.models import CalcDeal
from modules.deal_calculator.schemas import EstimateRequest
from modules.deal_calculator.seed import DEFAULT_BUNDLE
from modules.deal_calculator.seed import load_bundle as seed_calculator
from modules.investments.service import timeline
from modules.radar import service as radar
from modules.radar.signals import detect_signals, insights
from modules.readmodels import service as readmodels


def values(rows):

    return [r.model_dump(mode="json", exclude={"calculated_at"}) for r in rows]


def test_prepared_radar_and_timeline_equal_live_results_without_recalculating(
    business_db, monkeypatch
):
    session, _ = business_db
    load_bundle(session, read_bundle(get_settings().demo_bundle_path))
    session.commit()
    live = radar.heatmap(session)
    white = radar.white_spaces(session)
    calendar = timeline(session)
    assert readmodels.rebuild(session) == 7
    session.commit()
    monkeypatch.setattr(radar, "_cells", Mock(side_effect=AssertionError("live recomputation")))
    assert values(radar.heatmap(session)) == values(live)
    assert values(radar.white_spaces(session)) == values(white)
    assert values(timeline(session)) == values(calendar)
    first = live[0]
    selected = radar.heatmap(
        session, region_id=first.region_id, industry_group=first.industry_group
    )
    assert selected and all(c.region_id == first.region_id for c in selected)
    assert selected[0].potential_score == first.potential_score


def test_changed_revision_and_expired_snapshot_use_live_fallback(business_db, monkeypatch):
    session, _ = business_db
    load_bundle(session, read_bundle(get_settings().demo_bundle_path))
    session.commit()
    readmodels.rebuild(session)
    session.commit()
    assert readmodels.get_snapshot(session, "radar", "region") is not None
    readmodels.mark_changed(session)
    session.commit()
    assert readmodels.get_snapshot(session, "radar", "region") is None
    assert radar.heatmap(session)
    readmodels.rebuild(session)
    session.commit()
    row = session.get(ReadModelSnapshot, readmodels.snapshot_key("radar", "region"))
    row.calculated_at = datetime.now(UTC) - timedelta(hours=2)
    session.commit()
    assert readmodels.get_snapshot(session, "radar", "region") is None
    assert radar.heatmap(session)


def test_case_registry_signals_have_evidence_and_do_not_invent_federal_expansion(business_db):
    session, _ = business_db
    data = read_case(get_settings().case_workbook_path)
    expected = sum(bool(r.attributes.get("registry_new")) for r in data.companies)
    assert expected > 0
    import_case(session, get_settings().case_workbook_path)
    session.commit()
    assert session.scalar(select(func.count(MarketEntrySignal.id))) == expected
    assert detect_signals(session) == 0
    rows = insights(session, limit=500)
    assert len(rows) == expected
    assert {r["signal_type"] for r in rows} == {"new_registry_company"}
    assert all(r["source_id"] and r["evidence"] and not r["is_synthetic"] for r in rows)


def test_cross_region_observation_requires_verified_inn_and_real_sources(business_db):
    session, _ = business_db
    regions = [Region(name="First", code="TEST-A"), Region(name="Second", code="TEST-B")]
    session.add_all(regions)
    session.flush()
    mapping = {r.code: r.id for r in regions}
    rows = [
        RawCompany(
            source="real-registry",
            external_id=str(i),
            name="Company",
            inn="7710137066",
            region_code=region.code,
        )
        for i, region in enumerate(regions)
    ]
    load_companies(session, rows, {}, mapping)
    session.flush()
    assert detect_signals(session) == 1
    session.commit()
    row = insights(session)[0]
    assert row["signal_type"] == "cross_region_observation" and row["confidence"] == "low"
    assert "не подтверждённое" in row["evidence"]
    assert detect_signals(session) == 0


@pytest.fixture
def calculator_data(business_db):
    session, _ = business_db
    seed_calculator(session, json.loads(DEFAULT_BUNDLE.read_text(encoding="utf-8")))
    return session


def test_calculator_loads_pretrained_artifact_without_training_in_request(
    calculator_data, monkeypatch
):
    session = calculator_data
    monkeypatch.setattr(calculator, "win_model", Mock(side_effect=AssertionError("HTTP training")))
    result = calculator.estimate(
        session, EstimateRequest(object_type="residential", area_m2=5000), None
    )
    assert result.estimate["optimum"] > 0
    assert result.win_model and result.win_model["type"] == "multifactor"
    assert artifacts.prepare(session) is False


def test_modified_training_data_invalidates_same_length_artifact(calculator_data, monkeypatch):
    session = calculator_data
    regions = calculator.Regions(session)
    assert artifacts.load(session, calculator._deals(session), regions) is not None
    row = session.scalar(select(CalcDeal).order_by(CalcDeal.id))
    row.contract_value += Decimal("1")
    session.commit()
    assert artifacts.load(session, calculator._deals(session), regions) is None
    monkeypatch.setattr(calculator, "win_model", Mock(side_effect=AssertionError("HTTP training")))
    result = calculator.estimate(session, EstimateRequest(area_m2=5000), None)
    assert result.estimate["optimum"] > 0
    assert any("устарела" in warning for warning in result.warnings)


def test_tampered_artifact_is_rejected_before_deserialization(calculator_data, monkeypatch):
    session = calculator_data
    artifact = session.get(ModelArtifact, artifacts.KEY)
    artifact.payload = b"untrusted-pickle"
    session.commit()
    decoder = Mock(side_effect=AssertionError("unsafe decode"))
    monkeypatch.setattr(artifacts.pickle, "loads", decoder)
    assert artifacts.load(session, calculator._deals(session), calculator.Regions(session)) is None
    decoder.assert_not_called()


def test_project_and_tender_updates_keep_identity_known_zero_and_emit_changes(business_db):
    session, _ = business_db
    project = {
        "source": "real-test",
        "external_id": "P1",
        "title": "Building",
        "stage": "design",
        "estimated_budget": 10,
    }
    tender = {"source": "real-test", "external_id": "T1", "title": "Tender", "price": 100}
    load_projects(session, [project], {}, {}, {}, "test-rules")
    load_tenders(session, [tender], {}, {})
    session.commit()
    original = session.scalar(select(InvestmentProject))
    original_id, source_id = original.id, original.source_id
    project.update(title="Building UPDATED", stage="construction", estimated_budget=0)
    tender.update(price=0, status="closed")
    assert load_projects(session, [project], {}, {}, {}, "test-rules").projects_updated == 1
    assert load_tenders(session, [tender], {}, {}).tenders_updated == 1
    session.commit()
    row = session.scalar(select(InvestmentProject))
    assert row.id == original_id and row.source_id != source_id and row.estimated_budget == 0
    row = session.scalar(select(Tender))
    assert row.price == 0 and row.status == "closed"
    assert set(session.scalars(select(DomainEvent.event_type))) == {
        "investment.new",
        "investment.changed",
        "tender.new",
        "tender.changed",
    }
    load_projects(session, [project], {}, {}, {}, "test-rules")
    load_tenders(session, [tender], {}, {})
    session.commit()
    assert session.scalar(select(func.count(DomainEvent.id))) == 4
