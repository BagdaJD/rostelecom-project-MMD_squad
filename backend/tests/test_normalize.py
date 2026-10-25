"""Нормализация, ИНН и ключ объединения дублей — критерий «чистота, логика»."""

from __future__ import annotations

from ingestion.normalize import (
    RawCompany,
    clean_revenue,
    is_valid_inn,
    match_key,
    normalize_name,
    payload_hash,
)


def test_normalize_name_drops_forms_and_punctuation():
    assert normalize_name("  ООО «Ромашка» ") == "ромашка"
    assert normalize_name("ПАО «Сибнефтемаш»") == "сибнефтемаш"
    assert normalize_name("АО Уралгазстрой") == "уралгазстрой"
    assert normalize_name(None) == ""


def test_normalize_name_keeps_meaningful_words():
    assert normalize_name("Молочный комбинат Заря") == "молочный комбинат заря"


def test_inn_validation():
    assert is_valid_inn("7710137066")
    assert not is_valid_inn("7710137067")
    assert not is_valid_inn("771013706")
    assert not is_valid_inn(None)
    assert not is_valid_inn("не номер")
    assert is_valid_inn("500100732259")
    assert not is_valid_inn("500100732250")


def _record(**kwargs) -> RawCompany:
    base = dict(source="demo", external_id="X1", name="Ромашка")
    base.update(kwargs)
    return RawCompany(**base)


def test_match_prefers_inn_over_name():
    decision = match_key(_record(name="ООО Ромашка", inn="7710137066"))
    assert decision.method == "inn"
    assert decision.confidence == 1.0
    assert decision.company_key == "inn:7710137066"


def test_name_match_requires_region_and_is_not_confident():
    without_region = match_key(_record(name="Ромашка"))
    assert without_region.method == "new"

    with_region = match_key(_record(name="ООО «Ромашка»", region_code="RU-TYU"))
    assert with_region.method == "name_region"
    assert with_region.confidence < 1.0

    again = match_key(_record(name="Ромашка", region_code="RU-TYU"))
    assert again.company_key == with_region.company_key


def test_invalid_inn_falls_back_to_name_region():
    decision = match_key(_record(name="Ромашка", inn="123", region_code="RU-TYU"))
    assert decision.method == "name_region"


def test_clean_revenue_preserves_known_zero_and_drops_negative():
    cleaned = clean_revenue({2023: 100.0, 2024: 0.0, 2025: -5.0, 2026: None})
    assert cleaned == {2023: 100.0, 2024: 0.0}
    assert clean_revenue(None) == {}


def test_payload_hash_is_stable_and_key_order_independent():
    a = payload_hash({"b": 1, "a": 2})
    b = payload_hash({"a": 2, "b": 1})
    assert a == b
    assert a != payload_hash({"a": 2, "b": 3})
