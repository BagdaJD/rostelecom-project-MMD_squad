"""Импорт реальных контрактов из таблицы ЕИС (infra/scripts/import_contracts.py).

Значения в строках ниже — тестовые, не реальные контракты.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "scripts" / "import_contracts.py"
spec = importlib.util.spec_from_file_location("import_contracts", SCRIPT)
contracts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contracts)  # type: ignore[union-attr]


def row(**kw) -> dict:
    base = {
        "Номер в ЕИС": "TEST-1", "Ссылка": "https://example.test/1",
        "Предмет контракта": "Устройство системы диспетчеризации здания школы",
        "Заказчик": "Тестовый заказчик", "ИНН заказчика": "", "Регион": "Ростовская обл.",
        "Город": "Ростов-на-Дону", "Тип объекта": "соцобъект", "Площадь, м²": "3 200",
        "Системы": "Электроснабжение, Отопление", "Уровень": "базовый", "Закон": "44",
        "Начальная цена, руб": "1 500 000", "Цена контракта, руб": "1 290 000,50",
        "Ставки других участников, руб": "1350000, 1 410 000", "Дата контракта": "2025-06-15",
    }
    base.update(kw)
    return base


def test_template_example_row_is_skipped():
    deals, problems = contracts.convert([row(**{"Номер в ЕИС": "ПРИМЕР-0001"})])
    assert deals == [] and problems == []


def test_contract_becomes_won_deal_and_bids_become_lost():
    deals, problems = contracts.convert([row()])
    assert problems == []
    won = [d for d in deals if d["outcome"] == "won"]
    lost = [d for d in deals if d["outcome"] == "lost"]
    assert len(won) == 1 and len(lost) == 2
    assert won[0]["contract_value"] == pytest.approx(1_290_000.5)
    assert sorted(d["contract_value"] for d in lost) == [1_350_000, 1_410_000]
    for d in deals:
        assert d["retro_price_basis"] == "contract"
        assert d["financing_scheme"] == "budget"  # 44-ФЗ → госзаказчик
        assert d["object_type"] == "social" and d["region_code"] == "RU-ROS"
        assert d["cost_value"] > 0 and d["scope"]["cost_basis"] == "estimated_by_area"
        assert d["scope"]["features"] == ["Электроснабжение", "Отопление"]


def test_markup_is_comparable_with_calculator():
    deals, _ = contracts.convert([row()])
    won = next(d for d in deals if d["outcome"] == "won")
    # себестоимость оценена тем же расчётом, что и в калькуляторе → наценка в разумных пределах
    assert 0.5 < won["contract_value"] / won["cost_value"] < 10


def test_rows_without_price_or_area_are_reported():
    deals, problems = contracts.convert([row(**{"Площадь, м²": ""})])
    assert deals == [] and "Площадь" in problems[0]


def test_object_type_guessed_from_subject_when_column_empty():
    deals, _ = contracts.convert([row(**{"Тип объекта": "",
                                         "Предмет контракта": "Диспетчеризация склада"})])
    assert deals[0]["object_type"] == "warehouse"


def test_reads_excel_and_google_sheets_csv(tmp_path):
    header = list(row())
    values = list(row().values())
    excel = tmp_path / "excel.csv"
    excel.write_text(";".join(header) + "\n" + ";".join(values) + "\n", encoding="utf-8-sig")
    import csv

    google = tmp_path / "google.csv"
    with google.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)  # запятая; ячейки со списками Google берёт в кавычки
        writer.writerow(header)
        writer.writerow(values)
    for path in (excel, google):
        rows = contracts.read_rows(path)
        assert rows[0]["Системы"] == "Электроснабжение, Отопление"
        deals, problems = contracts.convert(rows)
        assert not problems and len(deals) == 3
