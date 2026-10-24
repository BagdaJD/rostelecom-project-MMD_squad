"""Тесты ML-функций и нормализации. БД не требуется — это чистые функции.

Запуск: cd backend && pytest -q
"""

from __future__ import annotations

import pytest

from ml.deal_estimator import Analog, EstimateInput, estimate_deal, similarity
from ml.needs import UNKNOWN, classify_need, contact_window
from ml.scoring import (
    PotentialInput,
    is_white_space,
    quartile_cut,
    score_potential,
)


def test_score_potential_is_bounded_and_explained():
    strong = PotentialInput(
        revenue_sum=1000, revenue_sum_max=1000, growth_share=0.25, companies_count=50,
        companies_count_max=50, active_projects=10, active_projects_max=10,
        open_tenders=5, open_tenders_max=5,
    )
    weak = PotentialInput()
    top = score_potential(strong)
    bottom = score_potential(weak)

    assert 0 <= bottom.score <= top.score <= 100
    assert top.score == pytest.approx(100.0, abs=0.1)
    assert top.factors, "скоринг обязан возвращать вклады признаков"
    assert sum(f.contribution for f in top.factors) == pytest.approx(top.score, abs=0.2)


def test_missing_data_does_not_inflate_score():
    """Пропуск даёт вклад 0, а не среднее: иначе карта врёт."""
    partial = PotentialInput(revenue_sum=500, revenue_sum_max=1000)
    result = score_potential(partial)
    assert 0 < result.score < 40


def test_white_space_rule_uses_quartiles():
    values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    p_cut = quartile_cut(values, 0.75)
    presence_cut = quartile_cut(values, 0.25)
    assert p_cut > presence_cut
    assert is_white_space(potential=p_cut, presence=presence_cut, p_cut=p_cut,
                          presence_cut=presence_cut)
    assert not is_white_space(potential=p_cut - 1, presence=presence_cut, p_cut=p_cut,
                              presence_cut=presence_cut)
    assert not is_white_space(potential=100, presence=100, p_cut=p_cut, presence_cut=presence_cut)


def test_quartile_of_single_value():
    assert quartile_cut([42.0], 0.75) == 42.0
    assert quartile_cut([], 0.75) == 0.0


@pytest.mark.parametrize(
    "title,description,expected",
    [
        ("Строительство теплицы с диспетчеризацией", "АСУ ТП и датчики климата", "iot_asu_tp"),
        ("Организация канала связи", "оптическая линия до объекта", "connectivity"),
        ("Поставка серверного оборудования и СХД", "виртуализация", "it_infrastructure"),
        ("Видеонаблюдение по периметру", "128 камер", "video_surveillance"),
    ],
)
def test_classify_need_finds_evidence(title, description, expected):
    predictions = classify_need(title, description)
    categories = [p.category for p in predictions]
    assert expected in categories
    top = next(p for p in predictions if p.category == expected)
    # Доказательство обязательно: без фрагмента текста вывод необъясним.
    assert top.evidence and len(top.evidence) > 3
    assert 0 < top.probability <= 0.9
    assert top.rule_id.startswith("rule:")


def test_classify_need_without_markers_is_honest():
    predictions = classify_need("Поставка канцелярских товаров", None)
    assert [p.category for p in predictions] == [UNKNOWN]
    assert predictions[0].evidence is None


def test_classify_need_empty_input():
    assert classify_need("", None)[0].category == UNKNOWN


def test_contact_window_covers_all_stages():
    for stage in ("design", "modernization", "construction", "launch"):
        assert contact_window(stage)
    assert contact_window("completed") is None


def _pool() -> list[Analog]:
    return [
        Analog(1, "Канал связи для склада", 40_000_000, "connectivity", "large", 10,
               "contract", ("works_cabling", "oborudovanie_server")),
        Analog(2, "Канал связи для офиса", 8_000_000, "connectivity", "small", 10,
               "synthetic", ("works_cabling",)),
        Analog(3, "ЦОД для клиники", 52_000_000, "it_infrastructure", "large", 20,
               "contract", ("oborudovanie_server",)),
    ]


def test_estimate_prefers_similar_analog():
    query = EstimateInput(project_type="connectivity", scale="large", region_id=10,
                          works=["works_cabling"], equipment=["oborudovanie_server"])
    result = estimate_deal(query, _pool(), top_k=3)

    assert result.price_min < result.price_optimum < result.price_max
    assert result.comparables[0]["deal_id"] == 1
    assert result.comparables[0]["similarity"] == max(
        c["similarity"] for c in result.comparables
    )
    # Среди аналогов есть контрактные цены → ложной тревоги про синтетику быть не должно.
    assert result.data_quality == "sufficient"


def test_estimate_warns_when_all_analogs_synthetic():
    """Демо-набор целиком синтетический: пользователь обязан видеть предупреждение."""
    pool = [
        Analog(1, "Канал связи для склада", 40_000_000, "connectivity", "large", 10,
               "synthetic", ("works_cabling", "oborudovanie_server")),
        Analog(2, "Канал связи для офиса", 8_000_000, "connectivity", "large", 10,
               "synthetic", ("works_cabling", "oborudovanie_server")),
    ]
    query = EstimateInput(project_type="connectivity", scale="large", region_id=10,
                          works=["works_cabling"], equipment=["oborudovanie_server"])
    result = estimate_deal(query, pool, top_k=3)
    assert result.warning and "синтетич" in result.warning.lower()


def test_estimate_warns_on_weak_similarity():
    query = EstimateInput(project_type="connectivity", works=["nothing_matches"])
    result = estimate_deal(query, _pool(), top_k=3)
    assert result.warning and "сходств" in result.warning.lower()
    assert result.data_quality == "limited"


def test_estimate_regional_coefficient_moves_price():
    pool = _pool()
    base = EstimateInput(project_type="connectivity", scale="large", region_id=10,
                         works=["works_cabling"])
    far = EstimateInput(project_type="connectivity", scale="large", region_id=10,
                        works=["works_cabling"], regional_coefficient=1.15)
    assert estimate_deal(far, pool).price_optimum > estimate_deal(base, pool).price_optimum


def test_estimate_without_analogs_refuses_to_invent():
    query = EstimateInput(project_type="quantum_cryogenics")
    result = estimate_deal(query, _pool())
    assert result.price_optimum == 0
    assert result.data_quality == "insufficient"
    assert result.warning


def test_similarity_bounded_and_type_dominant():
    query = EstimateInput(project_type="connectivity", scale="large", region_id=10)
    same = Analog(1, "a", 1, "connectivity", "large", 10)
    other = Analog(2, "b", 1, "it_infrastructure", "small", 99)
    assert similarity(query, same) > similarity(query, other)
    assert similarity(query, same) <= 1.0
