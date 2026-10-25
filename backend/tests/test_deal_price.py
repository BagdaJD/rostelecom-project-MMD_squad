"""Гибридная вилка: себестоимость × наценка аналогов, шанс выиграть, оплата."""

from __future__ import annotations

import math
import random

import pytest

from ml.deal_pricing import (
    Analog,
    EstimateInput,
    PriceConfig,
    estimate_hybrid,
    fit_win_model,
    local_win_model,
    payment_options,
    weighted_quantile,
)

COST = 668_528.74


def market(n: int = 120, seed: int = 7, i50: float = 1.42, k: float = 18.0) -> list[Analog]:
    """Исходы сделок по «истинной» логистике — модель должна её восстановить."""
    rnd = random.Random(seed)
    pool = []
    for i in range(n):
        idx = rnd.uniform(1.15, 1.65)
        won = rnd.random() < 1 / (1 + math.exp(k * (idx - i50)))
        cost = rnd.uniform(300_000, 2_000_000)
        pool.append(Analog(1000 + i, f"Сделка {i}", cost * idx, "dispatching", None, 61,
                           "synthetic", ("Отопление",), cost_value=cost,
                           outcome="won" if won else "lost", area_m2=rnd.uniform(1000, 9000)))
    return pool


def similar() -> list[Analog]:
    rows = [(3800, 590_000, 1.36, "won"), (5200, 742_000, 1.30, "won"),
            (6100, 905_000, 1.45, "lost"), (4000, 615_000, 1.30, "won"),
            (7500, 1_060_000, 1.40, "won"), (2900, 455_000, 1.42, "lost"),
            (3300, 520_000, 1.48, "lost")]
    systems = ("Электроснабжение", "Отопление", "Водоснабжение", "Вентиляция",
               "Кондиционирование")
    return [Analog(i, f"ТЦ {a} м²", c * x, "dispatching", None, 61, "synthetic", systems,
                   cost_value=c, outcome=o, area_m2=a)
            for i, (a, c, x, o) in enumerate(rows, 1)]


QUERY = EstimateInput(project_type="dispatching", region_id=61, area_m2=4500,
                      works=["Электроснабжение", "Отопление", "Водоснабжение", "Вентиляция",
                             "Кондиционирование"])


def test_weighted_quantile_basics():
    assert weighted_quantile([1, 2, 3], [1, 1, 1], 0.5) == pytest.approx(2)
    assert weighted_quantile([1, 2, 3], [1, 1, 10], 0.5) > 2.5
    assert weighted_quantile([5], [1], 0.9) == 5


def test_win_model_recovers_market_response():
    model = fit_win_model(market())
    assert model is not None and model.b > 0
    assert model.p(1.25) > 0.8 > 0.2 > model.p(1.6)
    assert model.p(1.42) == pytest.approx(0.5, abs=0.15)


def test_win_model_needs_enough_outcomes():
    assert fit_win_model(market(n=10)) is None


def test_hybrid_range_is_ordered_and_above_cost_floor():
    result = estimate_hybrid(QUERY, similar() + market(), COST)
    assert result.estimator_mode == "hybrid"
    assert COST / 0.85 <= result.price_min + 0.01
    assert result.price_min <= result.price_optimum <= result.price_max
    assert result.margin_min <= result.margin_optimum <= result.margin_max
    assert 0 < result.win_probability < 100


def test_optimum_maximizes_expected_profit_inside_range():
    result = estimate_hybrid(QUERY, similar() + market(), COST)
    model = local_win_model(QUERY, similar() + market(), PriceConfig())

    def expected(price: float) -> float:
        return (price - COST) * model.p(price / COST)

    assert result.optimum_method == "max_expected_profit"
    assert expected(result.price_optimum) >= expected(result.price_min) - 1
    assert expected(result.price_optimum) >= expected(result.price_max) - 1


def test_curve_for_margin_chart():
    result = estimate_hybrid(QUERY, similar() + market(), COST)
    assert len(result.curve) == PriceConfig().curve_points
    margins = [p["margin_pct"] for p in result.curve]
    wins = [p["win_prob"] for p in result.curve]
    assert margins == sorted(margins)
    assert wins == sorted(wins, reverse=True)


def test_most_similar_analogs_come_first():
    result = estimate_hybrid(QUERY, similar() + market(), COST)
    top = result.comparables[0]
    assert top["area_m2"] in {3800, 5200, 4000}
    assert top["price_index"] == pytest.approx(top["contract_value"] / top["cost_value"])


def test_without_analogs_falls_back_to_target_margin():
    result = estimate_hybrid(QUERY, [], COST)
    assert result.estimator_mode == "rule_based"
    assert result.price_min == pytest.approx(COST / 0.85, abs=0.01)
    assert result.price_optimum == pytest.approx(COST / 0.75, abs=0.01)
    assert result.win_probability is None
    assert any("мало" in w for w in result.warnings)


def test_synthetic_basis_is_flagged():
    result = estimate_hybrid(QUERY, similar() + market(), COST)
    text = " ".join(result.warnings)
    assert "синтетич" in text and "эвристика" in text


def test_zero_cost_is_rejected():
    with pytest.raises(ValueError):
        estimate_hybrid(QUERY, similar(), 0)


def test_payment_options():
    opts = {o["scheme"]: o for o in payment_options(889_143)}
    assert opts["capex"]["total"] == 889_143
    assert opts["installment"]["monthly"] == pytest.approx(82_365, abs=2)
    assert opts["installment"]["total"] > 889_143
    assert opts["opex"]["monthly"] == pytest.approx(33_044 + 5_000, abs=2)


def test_win_model_falls_back_to_whole_pool_when_neighbors_are_few():
    config = PriceConfig(win_model_neighbors=5)
    assert local_win_model(QUERY, similar() + market(), config) is not None
