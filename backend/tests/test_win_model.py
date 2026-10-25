"""Многофакторная модель шанса выиграть: находит заложенные эффекты и честно проверяется."""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

import pytest

pytest.importorskip("sklearn")

from ml.deal_pricing import Analog, EstimateInput, estimate_hybrid  # noqa: E402
from ml.win_model import DealRow, train  # noqa: E402


def market(n: int = 600, seed: int = 3) -> list[DealRow]:
    """Рынок с известными эффектами: госзаказчик −0,06, сервис +0,03, эксперт +0,03."""
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        budget = rnd.random() < 0.3
        payment = rnd.choice(["capex", "installment", "opex"])
        level = rnd.choice(["basic", "advanced", "expert"])
        shift = (-0.06 if budget else 0) + (0.03 if payment == "opex" else 0) + (
            0.03 if level == "expert" else 0)
        idx = rnd.uniform(1.15, 1.65)
        won = rnd.random() < 1 / (1 + math.exp(18 * (idx - 1.42 - shift)))
        rows.append(DealRow(idx, rnd.uniform(800, 12000), level, rnd.choice(["retail", "office"]),
                            "RU-ROS", payment, budget, "won" if won else "lost",
                            date(2023, 1, 1) + timedelta(days=i)))
    return rows


def query(**kw) -> DealRow:
    base = dict(price_index=1.0, area_m2=4500, project_level="advanced", object_type="retail",
                zone="RU-ROS", payment_scheme="capex", budget_customer=False)
    base.update(kw)
    return DealRow(**base)


def test_too_little_data_returns_none():
    assert train(market(n=30)) is None


def test_validation_is_time_based_with_baseline():
    model = train(market())
    q = model.quality
    assert (q.n_train, q.n_test) == (450, 150)
    assert q.auc is not None and q.auc > 0.7
    assert q.auc_baseline is not None
    assert q.basis == "synthetic"


def test_higher_markup_means_lower_chance():
    bound = train(market()).bind(query())
    probs = bound.curve([1.2, 1.3, 1.4, 1.5, 1.6])
    assert probs == sorted(probs, reverse=True)
    assert bound.p(1.3) == pytest.approx(probs[1])


def test_model_recovers_planted_effects():
    model = train(market())
    gov = model.bind(query(budget_customer=True)).p(1.40)
    private = model.bind(query(budget_customer=False)).p(1.40)
    opex = model.bind(query(payment_scheme="opex")).p(1.40)
    assert gov < private - 0.05, "госзаказчик должен снижать шанс"
    assert opex > private, "сервисная модель должна повышать шанс"


def test_factors_explain_in_percentage_points():
    factors = train(market()).bind(query(budget_customer=True)).factors(1.40)
    assert factors == sorted(factors, key=lambda f: -abs(f["delta_pp"]))
    gov = next(f for f in factors if f["factor"] == "budget_customer")
    assert gov["delta_pp"] < 0 and gov["value"] == "да" and gov["typical"] == "нет"


def test_hybrid_uses_multifactor_model_and_reports_it():
    model = train(market())
    analogs = [Analog(i, f"ТЦ {i}", 900_000 * x, "dispatching", None, 1, "synthetic",
                      ("Отопление",), cost_value=900_000, outcome="won", area_m2=4000)
               for i, x in enumerate([1.30, 1.34, 1.38, 1.42, 1.36], 1)]
    q = EstimateInput(project_type="dispatching", region_id=1, works=["Отопление"], area_m2=4000)
    result = estimate_hybrid(q, analogs, 668_528.74, win_model=model.bind(query()))
    assert result.win_model["type"] == "multifactor"
    assert result.win_model["auc"] is not None and result.win_model["factors"] is not None
    assert result.optimum_method == "max_expected_profit"
    assert result.price_min <= result.price_optimum <= result.price_max


def test_missing_features_count_as_typical_and_labels_are_human():
    model = train(market())
    factors = model.bind(query(zone=None, object_type="retail")).factors(1.40)
    names = {f["factor"] for f in factors}
    assert "zone" not in names  # регион не указан → типичный, не отдельная категория
    labels = " ".join(f["value"] + f["typical"] for f in factors)
    assert "unknown" not in labels and "retail" not in labels
