"""Себестоимость по справочникам кейса: контрольный пример «ТЦ в Ростове» считается руками."""

from __future__ import annotations

import pytest

from ml.deal_cost import (
    OBJECT_TYPES,
    CatalogItem,
    CostInput,
    CustomLine,
    LineInput,
    PricingConfig,
    calculate_cost,
    suggest_items,
    urgency_coefficient,
)

# Значения из МОД3_Таб4 (цена, коэффициент сложности группы).
CATALOG = {
    code: CatalogItem(code, name, group, price, k)
    for code, name, group, price, k in [
        ("el_01", "Смарт-счетчик (3-фазный)", "Электроснабжение", 8500, 1.2),
        ("el_02", "Датчик качества электроэнергии", "Электроснабжение", 12000, 1.2),
        ("ht_01", "Тепловычислитель (узел учета)", "Отопление", 22000, 1.4),
        ("ht_02", "Датчик температуры (погружной)", "Отопление", 1800, 1.4),
        ("ws_01", "Ультразвуковой расходомер", "Водоснабжение", 14000, 1.1),
        ("ws_03", "Датчик протечки воды", "Водоснабжение", 1200, 1.1),
        ("vn_01", "Контроллер ПВУ", "Вентиляция", 28000, 1.6),
        ("vn_02", "Датчик CO2", "Вентиляция", 7500, 1.6),
        ("kd_01", "Контроллер VRF-системы", "Кондиционирование", 35000, 1.5),
        ("kd_02", "Датчик температуры/влажности", "Кондиционирование", 2800, 1.5),
    ]
}
TC_ITEMS = [LineInput(c, q) for c, q in [
    ("el_01", 12), ("el_02", 2), ("ht_01", 1), ("ht_02", 8), ("ws_01", 2),
    ("ws_03", 10), ("vn_01", 3), ("vn_02", 6), ("kd_01", 1), ("kd_02", 10)]]


def tc(**kw) -> CostInput:
    params = {"items": TC_ITEMS, "project_level": "advanced", "regional_coefficient": 1.1}
    params.update(kw)
    return CostInput(**params)


def test_control_example_matches_hand_calculation():
    # E = 394 400; W = 547 060 × 0,30 = 164 118; C = (E + W × 1,3) × 1,1
    result = calculate_cost(tc(), CATALOG)
    assert result.total == pytest.approx(668_528.74, abs=0.01)
    assert result.breakdown["equipment"] == pytest.approx(394_400 * 1.1)
    assert result.points == 55


def test_breakdown_sums_to_total_and_follows_table3_shares():
    result = calculate_cost(tc(), CATALOG)
    assert sum(result.breakdown.values()) == pytest.approx(result.total, abs=0.05)
    b = result.breakdown
    assert b["commissioning"] / b["design"] == pytest.approx(1.5)
    assert b["supervision"] / b["design"] == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("works", 668_528.74), ("installation", 770_963.60), ("equipment", 836_454.74)],
)
def test_complexity_interpretations(mode, expected):
    result = calculate_cost(tc(), CATALOG, PricingConfig(complexity_mode=mode))
    assert result.total == pytest.approx(expected, abs=0.01)


def test_project_level_is_monotonic():
    totals = [calculate_cost(tc(project_level=lvl), CATALOG).total
              for lvl in ("basic", "advanced", "expert")]
    assert totals == sorted(totals) and totals[0] < totals[-1]


def test_unknown_level_is_rejected():
    with pytest.raises(ValueError):
        calculate_cost(tc(project_level="ultra"), CATALOG)


def test_urgency_only_when_deadline_is_tighter_than_norm():
    config = PricingConfig()
    assert urgency_coefficient(None, 55, config) == 1.0
    assert urgency_coefficient(6, 55, config) == 1.0  # норма 1,55 мес.
    tight = urgency_coefficient(1.0, 55, config)
    tighter = urgency_coefficient(0.5, 55, config)
    assert 1.0 < tight < tighter <= config.urgency_max
    assert urgency_coefficient(0.01, 10_000, config) == config.urgency_max


def test_urgency_raises_total():
    normal = calculate_cost(tc(duration_months=3), CATALOG).total
    rushed = calculate_cost(tc(duration_months=0.8), CATALOG).total
    assert rushed > normal


def test_unique_solution_coefficient_applied():
    base = calculate_cost(tc(), CATALOG).total
    unique = calculate_cost(tc(has_unique_solution=True), CATALOG).total
    assert unique == pytest.approx(base * PricingConfig().unique_solution_coefficient, abs=0.05)


def test_unknown_code_is_reported_not_invented():
    result = calculate_cost(tc(items=[*TC_ITEMS, LineInput("zz_99", 5)]), CATALOG)
    assert result.total == pytest.approx(668_528.74, abs=0.01)
    assert any("zz_99" in w for w in result.warnings)


def test_nonstandard_lines_get_reserve_and_warning():
    custom = [CustomLine("Шлюз Modbus нестандартный", 2, 30_000, "equipment"),
              CustomLine("Лицензия SCADA", 1, 120_000, "software")]
    result = calculate_cost(tc(custom_lines=custom), CATALOG)
    assert result.breakdown["software"] == 120_000
    assert result.breakdown["reserve"] == pytest.approx((60_000 + 120_000) * 0.20)
    assert any("пресейл" in w for w in result.warnings)
    assert result.total > 668_528.74 + 60_000 + 120_000


def test_empty_composition_is_honest():
    result = calculate_cost(CostInput(items=[]), CATALOG)
    assert result.total == 0
    assert result.warnings


def test_factors_mark_source_of_each_parameter():
    sources = {f.factor: f.source for f in calculate_cost(tc(), CATALOG).factors}
    assert sources["project_level"] == "кейс"
    assert sources["regional_coefficient"] == "кейс"
    assert sources["urgency"] == "допущение"


def test_suggest_items_follows_object_type_and_area():
    small = {i.code: i.qty for i in suggest_items("retail", 1_000)}
    big = {i.code: i.qty for i in suggest_items("retail", 10_000)}
    assert not any(code.startswith(("gs_", "wo_")) for code in small)  # в ТЦ нет газа и КНС
    assert all(big[c] >= small[c] for c in small)
    assert all(isinstance(q, int) and q > 0 for q in big.values())
    assert set(OBJECT_TYPES) >= {"retail", "warehouse", "office", "social"}
