"""CSV калькулятора для Excel: «;», десятичная запятая, BOM; запятая в тексте — не разделитель."""

from __future__ import annotations

import csv
import io

from modules.deal_calculator.export import DEAL_HEADERS, excel_csv


def test_excel_csv_opens_in_russian_excel():
    rows = [{"estimate_id": 7, "area_m2": 4000.0, "cost_total": 788234.7, "margin_optimum": 24.07,
             "object": "Торговый объект, ТЦ «Север»", "approved_price": ""}]
    data = excel_csv(rows, DEAL_HEADERS)
    assert data.startswith(b"\xef\xbb\xbf"), "без BOM Excel портит кириллицу"
    header, line = list(csv.reader(io.StringIO(data[3:].decode("utf-8")), delimiter=";"))
    values = dict(zip(header, line, strict=True))
    assert values["Номер расчёта"] == "7"
    assert values["Площадь, м²"] == "4000"  # целое — без «,0»
    assert values["Себестоимость, руб"] == "788234,7"  # десятичная запятая
    assert values["Объект"] == "Торговый объект, ТЦ «Север»"
