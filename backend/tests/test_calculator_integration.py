"""Калькулятор на живой БД: данные кейса → себестоимость → вилка → утверждение → КП и CSV.

Работает только с таблицами calc_* (создаёт их сам). Без PostgreSQL тесты пропускаются.
Запуск: cd backend && pytest -q tests/test_calculator_integration.py
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select

from app.db.session import SessionLocal, engine
from modules.deal_calculator import export, proposal
from modules.deal_calculator import service as calculator
from modules.deal_calculator.models import CalcDeal, CalcEstimate, CalcPosition, CalcRegion
from modules.deal_calculator.schemas import EstimateRequest
from modules.deal_calculator.seed import DEFAULT_BUNDLE, create_tables, load_bundle

ROOT = Path(__file__).resolve().parents[2]
TC_ITEMS = [("el_01", 12), ("el_02", 2), ("ht_01", 1), ("ht_02", 8), ("ws_01", 2),
            ("ws_03", 10), ("vn_01", 3), ("vn_02", 6), ("kd_01", 1), ("kd_02", 10)]


def _db_available() -> bool:
    try:
        create_tables(engine)
        return True
    except Exception:  # noqa: BLE001 — отсутствие БД штатно для unit-прогона
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _db_available(), reason="нужен PostgreSQL"),
]


@pytest.fixture(scope="module", autouse=True)
def seeded() -> None:
    with SessionLocal() as session:
        load_bundle(session, json.loads(DEFAULT_BUNDLE.read_text(encoding="utf-8")))


def _rostov_id(session) -> int:
    return session.scalar(select(CalcRegion.id).where(CalcRegion.code == "RU-ROS-RND"))


def test_bundle_is_idempotent_and_complete() -> None:
    with SessionLocal() as session:
        second = load_bundle(session, json.loads(DEFAULT_BUNDLE.read_text(encoding="utf-8")))
        assert second["deals"] == 0 and second["positions"] == 0 and second["regions"] == 0
        assert session.scalar(select(func.count(CalcPosition.id))) == 20
        assert session.scalar(select(func.count(CalcDeal.id))
                              .where(CalcDeal.cost_value.is_not(None))) >= 400


def test_region_coefficient_is_inherited_from_zone() -> None:
    with SessionLocal() as session:
        k, label = calculator.Regions(session).coefficient(_rostov_id(session))
    assert k == pytest.approx(1.1)
    assert label == "г. Ростов-на-Дону"


def test_control_example_through_service() -> None:
    with SessionLocal() as session:
        payload = EstimateRequest(
            object_type="retail", area_m2=4500, project_level="advanced",
            region_id=_rostov_id(session), duration_months=3,
            items=[{"code": c, "qty": q} for c, q in TC_ITEMS],
        )
        result = calculator.estimate(session, payload, author_id=None)

    assert result.cost["total"] == pytest.approx(668_528.74, abs=0.01)
    assert result.estimator_mode == "hybrid"
    est = result.estimate
    assert result.cost["total"] < est["min"] <= est["optimum"] <= est["max"]
    assert len(result.curve) > 10 and result.comparables
    assert result.win_model is not None
    assert sum(float(b["amount"]) for b in result.breakdown) == pytest.approx(
        float(est["optimum"]), abs=1)
    with SessionLocal() as session:  # расчёт сохранён — по нему собирается КП
        row = session.get(CalcEstimate, result.estimate_id)
        assert row is not None and float(row.cost_total) == pytest.approx(668_528.74, abs=0.01)


def test_price_below_cost_cannot_be_approved_and_kp_uses_approved_price() -> None:
    with SessionLocal() as session:
        payload = EstimateRequest(object_type="office", area_m2=1500,
                                  region_id=_rostov_id(session))
        result = calculator.estimate(session, payload, author_id=None)
        with pytest.raises(ValueError):
            calculator.approve(session, result.estimate_id, result.cost["total"] * 0.9, None)
        price = float(result.estimate["optimum"]) + 10_000
        row = calculator.approve(session, result.estimate_id, price, None)
        assert float(row.approved_price) == pytest.approx(price)

        from docx import Document

        for variant in ("client", "internal"):
            content = proposal.build_proposal(session, result.estimate_id, variant)
            text = "\n".join(p.text for p in Document(io.BytesIO(content)).paragraphs)
            assert "Коммерческое предложение" in text
            assert ("Обоснование цены" in text) == (variant == "internal")

        deals_csv = export.export_csv(session, "deals", result.estimate_id).decode("utf-8-sig")
        assert deals_csv.splitlines()[0].startswith("Номер расчёта;")
        crm = export.export_csv(session, "crm", result.estimate_id).decode("utf-8-sig")
        assert "Утверждено" in crm and f"rtk-calc-{result.estimate_id}" in crm


def test_real_contracts_load_and_feed_the_model() -> None:
    """Контракты из таблицы ЕИС грузятся тем же загрузчиком, модель видит смешанные данные."""
    script = ROOT / "infra" / "scripts" / "import_contracts.py"
    spec = importlib.util.spec_from_file_location("import_contracts", script)
    contracts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contracts)  # type: ignore[union-attr]
    rows = [{"Номер в ЕИС": f"TEST-INT-{i}", "Предмет контракта": "Диспетчеризация школы",
             "Регион": "Ростовская обл.", "Тип объекта": "соцобъект",
             "Площадь, м²": str(2500 + 300 * i), "Уровень": "базовый", "Закон": "44",
             "Цена контракта, руб": str(700_000 + 40_000 * i),
             "Ставки других участников, руб": str(760_000 + 40_000 * i),
             "Дата контракта": f"2026-0{1 + i % 9}-10"} for i in range(5)]
    deals, problems = contracts.convert(rows)
    assert not problems
    pattern = "Контракт ЕИС № TEST-INT-%"
    with SessionLocal() as session:
        load_bundle(session, {"historical_deals": deals})
        try:
            loaded = session.scalars(select(CalcDeal).where(CalcDeal.title.like(pattern))).all()
            assert len(loaded) == 10
            assert all(d.region_code == "RU-ROS" and d.retro_price_basis == "contract"
                       for d in loaded)
            payload = EstimateRequest(object_type="social", area_m2=3000,
                                      region_id=_rostov_id(session), financing_scheme="budget")
            result = calculator.estimate(session, payload, author_id=None)
            if result.win_model and result.win_model.get("type") == "multifactor":
                assert result.win_model["basis"] == "mixed"
        finally:
            session.execute(delete(CalcDeal).where(CalcDeal.title.like(pattern)))
            session.commit()
