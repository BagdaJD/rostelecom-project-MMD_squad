#!/usr/bin/env python3
"""Реальные контракты из ЕИС (таблица, заполненная вручную) → бандл калькулятора.

ЕИС не даёт автоматическую выгрузку без согласования, поэтому контракты выписываются
руками в ``data/contracts/contracts.csv`` по шаблону ``contracts_template.csv``
(разделитель «;», списки внутри ячейки — через запятую).

Что получается из каждой строки:

* сделка «выиграли» по цене контракта (``retro_price_basis = contract``);
* по сделке «проиграли» на каждую ставку других участников из протокола — так модель шанса
  выиграть учится на настоящих исходах торгов;
* себестоимость оценивается тем же расчётом, что и в калькуляторе: состав подбирается по
  типу объекта и площади (``suggest_items``), цены — из каталога кейса. Поэтому наценка
  реального контракта сопоставима с наценкой нашего расчёта. В ``scope.cost_basis``
  остаётся пометка ``estimated_by_area``.

Запуск из корня репозитория::

    python3 infra/scripts/import_contracts.py                 # data/contracts/contracts.csv
    python3 infra/scripts/import_contracts.py --csv мой.csv

Загрузка в таблицы калькулятора (из папки backend)::

    python -m modules.deal_calculator.seed \
        --bundle modules/deal_calculator/data/contracts_bundle.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from ml.deal_cost import (  # noqa: E402
    OBJECT_TYPES,
    SYSTEM_TEMPLATES,
    CatalogItem,
    CostInput,
    PricingConfig,
    calculate_cost,
    guess_object_type,
    suggest_items,
)

CSV_PATH = ROOT / "data" / "contracts" / "contracts.csv"
CASE_BUNDLE = ROOT / "backend" / "modules" / "deal_calculator" / "data" / "case_bundle.json"
OUT = ROOT / "backend" / "modules" / "deal_calculator" / "data" / "contracts_bundle.json"

LEVELS = {"базовый": "basic", "продвинутый": "advanced", "экспертный": "expert"}
OBJECT_ALIASES = {
    "торговый объект": "retail", "тц": "retail", "склад": "warehouse", "логистика": "warehouse",
    "офис": "office", "администрация": "office", "производство": "industrial", "апк": "agro",
    "мкд": "residential", "жилой дом": "residential", "соцобъект": "social",
    "школа": "social", "больница": "social", "поликлиника": "social", "детсад": "social",
    "отдых и спорт": "hospitality", "спорт": "hospitality",
}
ZONES = {"ростовская обл.": "RU-ROS", "ростовская область": "RU-ROS", "юг": "ZONE-S",
         "центр": "ZONE-CEN", "северо-запад": "ZONE-NW", "урал": "ZONE-URV",
         "поволжье": "ZONE-URV", "сибирь": "ZONE-FES", "дальний восток": "ZONE-FES"}


def _money(value: str | None) -> float | None:
    if not value or not value.strip():
        return None
    text = value.replace("\xa0", "").replace(" ", "").replace("₽", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _list(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def _object_type(raw: str | None, subject: str) -> str:
    key = (raw or "").strip().lower()
    if key in OBJECT_TYPES:
        return key
    return OBJECT_ALIASES.get(key) or guess_object_type(subject)


def _catalog() -> tuple[dict[str, CatalogItem], dict[str, float]]:
    bundle = json.loads(CASE_BUNDLE.read_text(encoding="utf-8"))
    zones = {c["region_code"]: c["coefficient"] for c in bundle["coefficients"]}
    catalog = {p["code"]: CatalogItem(p["code"], p["name"], p["system_group"],
                                      p["price_typical"], p["complexity_coef"])
               for p in bundle["positions"]}
    return catalog, zones


def convert(rows: list[dict]) -> tuple[list[dict], list[str]]:
    catalog, zones = _catalog()
    deals: list[dict] = []
    problems: list[str] = []
    for n, row in enumerate(rows, start=2):  # строка 1 — заголовок
        number = (row.get("Номер в ЕИС") or "").strip()
        if not number or number.upper().startswith("ПРИМЕР"):
            continue
        subject = (row.get("Предмет контракта") or "").strip()
        price = _money(row.get("Цена контракта, руб"))
        area = _money(row.get("Площадь, м²"))
        if not price or not area:
            problems.append(f"строка {n} ({number}): нужны «Цена контракта» и «Площадь»")
            continue
        object_type = _object_type(row.get("Тип объекта"), subject)
        systems = [s for s in _list(row.get("Системы")) if s in SYSTEM_TEMPLATES] or None
        level = LEVELS.get((row.get("Уровень") or "").strip().lower(), "basic")
        zone = ZONES.get((row.get("Регион") or "").strip().lower(), "RU-ROS")
        cost = calculate_cost(
            CostInput(suggest_items(object_type, area, systems), level,
                      zones.get(zone, zones.get("ZONE-S", 1.1))),
            catalog, PricingConfig(),
        ).total
        if cost <= 0:
            problems.append(f"строка {n} ({number}): не удалось оценить себестоимость")
            continue
        law = (row.get("Закон") or "").strip()
        city = (row.get("Город") or "").strip()
        base = {
            "project_type": "dispatching",
            "object_type": object_type,
            "scale": "small" if area < 2000 else "medium" if area < 8000 else "large",
            "area_m2": area,
            "project_level": level,
            "region_code": zone,
            "cost_value": round(cost, 2),
            "retro_price_basis": "contract",
            "financing_scheme": "budget" if law == "44" else "own",
            "payment_scheme": "capex",
            "closed_at": (row.get("Дата контракта") or "").strip() or None,
            "scope": {"features": systems or OBJECT_TYPES[object_type]["systems"],
                      "cost_basis": "estimated_by_area", "eis_number": number,
                      "source_url": (row.get("Ссылка") or "").strip(),
                      "customer": (row.get("Заказчик") or "").strip(),
                      "customer_inn": (row.get("ИНН заказчика") or "").strip(),
                      "initial_price": _money(row.get("Начальная цена, руб")),
                      "law": law, "city": city},
        }
        title = f"Контракт ЕИС № {number}: {subject or OBJECT_TYPES[object_type]['label']}"
        deals.append({**base, "title": title[:500], "contract_value": price, "outcome": "won"})
        for i, bid in enumerate(_list(row.get("Ставки других участников, руб")), start=1):
            value = _money(bid)
            if value and value > 0:
                deals.append({**base, "title": f"{title[:480]} — ставка участника {i}",
                              "contract_value": value, "outcome": "lost"})
    return deals, problems


def read_rows(path: Path) -> list[dict]:
    """CSV из Excel (разделитель «;») или Google Таблиц («,») — определяем по заголовку."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        header = fh.readline()
        delimiter = ";" if header.count(";") >= header.count(",") else ","
        fh.seek(0)
        return list(csv.DictReader(fh, delimiter=delimiter))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    if not args.csv.exists():
        sys.exit(f"нет файла {args.csv}: скопируйте data/contracts/contracts_template.csv "
                 f"в contracts.csv и заполните")
    rows = read_rows(args.csv)
    deals, problems = convert(rows)
    bundle = {
        "_meta": {"generated_by": "infra/scripts/import_contracts.py",
                  "source_file": str(args.csv),
                  "notice": "Реальные контракты из ЕИС, внесённые вручную. Себестоимость "
                            "оценена по площади и каталогу кейса (cost_basis=estimated_by_area)."},
        "historical_deals": deals,
    }
    args.out.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    won = sum(d["outcome"] == "won" for d in deals)
    print(f"{args.out}: контрактов {won}, ставок проигравших {len(deals) - won}")
    for p in problems:
        print("  пропущено —", p)


if __name__ == "__main__":
    main()
