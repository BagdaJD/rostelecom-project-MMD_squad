#!/usr/bin/env python3
"""Импорт данных кейса (xlsx организаторов) в бандл калькулятора сделок.

Что берём из ``data/case/case_data_2026.xlsx``:

* МОД3_Таб1 — региональные коэффициенты (зоны) → ``regions`` + ``coefficients``;
* МОД3_Таб2 — уровни проекта → словарь ``project_level``;
* МОД3_Таб3 — доли работ от оборудования → словарь ``work_stage``;
* МОД3_Таб4 — каталог 20 позиций с ценой и сложностью → ``positions`` (не синтетика);
* МОД«2»_Таб1 — инвестпроекты Ростовской области: только чтобы распределение типов
  объектов в демо-сделках было как в кейсе (сами проекты в бандл не пишутся — это данные
  навигатора).

Чего в кейсе нет и что генерируется (помечено ``retro_price_basis = synthetic``):

* ``historical_deals`` — история сделок по диспетчеризации: себестоимость по формуле
  ``ml/deal_cost.py``, наценка и исход «выиграли/проиграли» — по заданной логистике.

Реестр МСП (МОД1) здесь не импортируется — это данные радара.

Бандл загружается в таблицы калькулятора: ``python -m modules.deal_calculator.seed``.

Запуск из корня репозитория (нужен openpyxl)::

    python3 infra/scripts/import_case_xlsx.py   # → modules/deal_calculator/data/case_bundle.json
    python3 infra/scripts/import_case_xlsx.py --deals 400 --seed 7
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from ingestion.normalize import normalize_name  # noqa: E402
from ml.deal_cost import (  # noqa: E402
    OBJECT_TYPES,
    CatalogItem,
    CostInput,
    LineInput,
    PricingConfig,
    calculate_cost,
    estimate_area_m2,
    guess_object_type,
    parse_area_m2,
    suggest_items,
)

XLSX = ROOT / "data" / "case" / "case_data_2026.xlsx"
OUT = ROOT / "backend" / "modules" / "deal_calculator" / "data" / "case_bundle.json"
CASE_SOURCE = "case_xlsx"
LICENSE = "данные кейса хакатона ПАО «Ростелеком», осень 2026"
TODAY_YEAR = 2026

# Зоны из МОД3_Таб1 → коды регионов-зон (родители для субъектов).
ZONE_CODES = {
    "Центральный": "ZONE-CEN",
    "Северо-Западный": "ZONE-NW",
    "Южный": "ZONE-S",
    "Уральский": "ZONE-URV",
    "Дальневосточный": "ZONE-FES",
}
ROSTOV = {"code": "RU-ROS", "name": "Ростовская область", "parent_code": "ZONE-S",
          "center": [39.72, 47.23]}
# Муниципалитеты из МОД«2». Центры — приблизительные (райцентры), для точки на карте.
MUNICIPALITIES = {
    "г. Ростов-на-Дону": ("RU-ROS-RND", [39.72, 47.23]),
    "Азовский район": ("RU-ROS-AZV", [39.42, 47.11]),
    "Неклиновский район": ("RU-ROS-NEK", [38.90, 47.42]),
    "Боковский район": ("RU-ROS-BOK", [41.83, 49.23]),
    "Каменский район": ("RU-ROS-KAM", [40.67, 48.53]),
    "Тарасовский район": ("RU-ROS-TAR", [40.17, 48.73]),
}
# Отрасли инвестпроектов (группы — как в кейсе).
INDUSTRIES = [
    {"code": "TEK", "name": "ТЭК", "group": "ТЭК", "okved": []},
    {"code": "TRADE", "name": "Торговля", "group": "Торговля", "okved": []},
    {"code": "TRANSPORT", "name": "Логистика и складское хозяйство", "group": "Логистика",
     "okved": []},
    {"code": "APK", "name": "АПК", "group": "АПК", "okved": []},
    {"code": "INDUSTRY", "name": "Промышленность", "group": "Промышленность", "okved": []},
    {"code": "SERVICES", "name": "Услуги населению", "group": "Услуги населению", "okved": []},
    {"code": "CONSTRUCTION", "name": "Жилищное строительство", "group": "Строительство",
     "okved": []},
    {"code": "HEALTH", "name": "Здравоохранение", "group": "Здравоохранение", "okved": []},
]
INDUSTRY_BY_OBJECT = {"retail": "TRADE", "warehouse": "TRANSPORT", "office": "SERVICES",
                      "industrial": "INDUSTRY", "agro": "APK", "residential": "CONSTRUCTION",
                      "social": "HEALTH", "hospitality": "SERVICES"}
LEVEL_CODES = {"Базовый": "basic", "Продвинутый": "advanced", "Экспертный": "expert"}
STAGE_CODES = {"Проектирование (ПИР)": "design", "Пуско-наладка (ПНР)": "commissioning",
               "Шеф-монтаж": "supervision"}


def _num(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".").rstrip("%")
    return float(text) / (100 if str(value).strip().endswith("%") else 1)


def _rows(ws) -> list[tuple]:
    return [r for r in ws.iter_rows(min_row=2, values_only=True) if any(c is not None for c in r)]


def read_zones(wb) -> tuple[list[dict], list[dict]]:
    regions, coefficients = [], []
    for name, coef, why in _rows(wb["МОД3_Таб1"]):
        key = next(k for k in ZONE_CODES if str(name).startswith(k))
        code = ZONE_CODES[key]
        regions.append({"code": code, "name": f"Зона: {name}", "kind": "zone"})
        coefficients.append({"region_code": code, "work_type": "all", "coefficient": _num(coef),
                             "effective_from": "2026-01-01", "note": str(why)})
    regions.append(ROSTOV)
    coefficients.append({"region_code": ROSTOV["code"], "work_type": "all",
                         "coefficient": next(c["coefficient"] for c in coefficients
                                             if c["region_code"] == "ZONE-S"),
                         "effective_from": "2026-01-01", "note": "как зона «Южный»"})
    for name, (code, center) in MUNICIPALITIES.items():
        regions.append({"code": code, "name": name, "parent_code": ROSTOV["code"],
                        "center": center, "center_is_approximate": True})
    return regions, coefficients


def read_dictionaries(wb) -> dict[str, list[dict]]:
    levels = [{"code": LEVEL_CODES[str(n)], "label": str(n), "value": _num(c),
               "description": str(d)} for n, c, d in _rows(wb["МОД3_Таб2"])]
    stages = [{"code": STAGE_CODES[str(n)], "label": str(n), "value": _num(share),
               "description": str(d)} for n, share, d in _rows(wb["МОД3_Таб3"])]
    return {
        "project_level": levels,
        "work_stage": stages,
        "payment_scheme": [
            {"code": "capex", "label": "Единовременно (по этапам работ)"},
            {"code": "installment", "label": "Рассрочка"},
            {"code": "opex", "label": "Сервисная модель (подписка)"},
        ],
        "object_type": [{"code": k, "label": v["label"]} for k, v in OBJECT_TYPES.items()],
    }


def read_positions(wb) -> list[dict]:
    out = []
    for group, code, name, unit, price, k in _rows(wb["МОД3_Таб4"]):
        out.append({"code": str(code), "name": str(name), "category": "equipment",
                    "system_group": str(group), "unit": str(unit),
                    "price_typical": _num(price), "complexity_coef": _num(k),
                    "price_period": "2026", "is_synthetic": False,
                    "source": f"{CASE_SOURCE}:МОД3_Таб4"})
    return out


def _stage(start: int, end: int, title: str) -> str:
    if re.search(r"модерниз|реконструк", title.lower()):
        return "modernization"
    if start > TODAY_YEAR:
        return "design"
    if end < TODAY_YEAR:
        return "completed"
    if end == TODAY_YEAR:
        return "launch"
    return "construction"


def _clean_title(value) -> str:
    """Схлопываем пробелы; внешние кавычки снимаем только парой, чтобы не порвать «...»."""
    title = re.sub(r"\s+", " ", str(value)).strip()
    for left, right in (("«", "»"), ('"', '"')):
        if title.startswith(left) and title.endswith(right) and title.count(left) == 1:
            title = title[1:-1].strip()
    return title


def read_projects(wb) -> tuple[list[dict], list[dict]]:
    # Лист называется «МОД"_Таб1» (опечатка организаторов) — ищем лист инвестпроектов.
    sheet = next(n for n in wb.sheetnames
                 if n.endswith("_Таб1") and not n.startswith(("МОД1", "МОД3")))
    projects, companies, seen = [], [], set()
    for row in _rows(wb[sheet]):
        no, mo, curator, key, initiator, title, start, end, budget, jobs = row[:10]
        title = _clean_title(title)
        initiator = re.sub(r"\s+", " ", str(initiator or "")).strip()
        object_type = guess_object_type(title)
        budget_rub = _num(budget) * 1_000_000 if budget is not None else None
        area = parse_area_m2(title)
        muni_code = MUNICIPALITIES.get(str(mo).strip(), (ROSTOV["code"], None))[0]
        projects.append({
            "source": f"{CASE_SOURCE}:МОД2", "external_id": f"MOD2-{no}",
            "title": title,
            "description": f"{title}. Инициатор: {initiator}. Куратор: {curator}. "
                           f"Ключевой проект: {key}. Новых рабочих мест: {jobs}.",
            "stage": _stage(int(start), int(end), title),
            "planned_start": f"{int(start)}-01-01", "planned_end": f"{int(end)}-12-31",
            "estimated_budget": budget_rub,
            "region_code": muni_code,
            "industry_code": "TEK" if "спг" in title.lower()
            else INDUSTRY_BY_OBJECT[object_type],
            "initiator_name": initiator,
            # Тот же ключ, что строит ingestion.normalize.match_key для компании без ИНН.
            "initiator_key": f"name:{normalize_name(initiator)}|{ROSTOV['code']}"
            if initiator else None,
            "object_type": object_type,
            "area_m2": area,
            "area_is_estimated": area is None,
            "area_m2_estimate": area or estimate_area_m2(object_type, budget_rub),
            "is_key_project": str(key).strip().lower() == "да",
            "new_jobs": jobs,
            "confidence": 1.0,
            "license_note": LICENSE,
        })
        if initiator and initiator.lower() not in seen:
            seen.add(initiator.lower())
            companies.append({"source": f"{CASE_SOURCE}:МОД2", "external_id": f"INIT-{no}",
                              "name": initiator, "region_code": ROSTOV["code"],
                              "license_note": LICENSE})
    return projects, companies


# ------------------------- синтетическая история сделок -----------------------------------
CITIES_ROSTOV = ["Ростов-на-Дону", "Батайск", "Таганрог", "Азов", "Новочеркасск", "Аксай",
                 "Шахты", "Волгодонск", "Каменск-Шахтинский", "Новошахтинск"]
OTHER_ZONES = [("ZONE-CEN", "Москва"), ("ZONE-NW", "Санкт-Петербург"),
               ("ZONE-URV", "Екатеринбург"), ("ZONE-FES", "Новосибирск")]
AREA_RANGE = {"retail": (800, 12000), "warehouse": (1500, 25000), "office": (500, 8000),
              "industrial": (2000, 30000), "agro": (1000, 20000),
              "residential": (3000, 20000), "social": (1500, 10000),
              "hospitality": (600, 9000)}
# Сдвиг типичной наценки: госзаказчики и жильё — больше конкуренции, производство — меньше.
TYPE_SHIFT = {"retail": 0.02, "warehouse": 0.0, "office": 0.01, "industrial": 0.04,
              "agro": 0.0, "residential": -0.03, "social": -0.06, "hospitality": 0.02}
I50, STEEPNESS = 1.42, 18.0
# Демо-допущения рынка (сдвиг порога наценки, при котором шанс выиграть = 50 %).
# Заложены в генератор, чтобы проверить: многофакторная модель (ml/win_model.py) должна
# их найти. Это не знание о реальном рынке — при подключении реальных сделок модель
# переобучится на них.
BUDGET_SHIFT = -0.05  # госзаказчик, торги по 44-ФЗ: конкуренция выше, дорогих не берут
LEVEL_SHIFT = {"basic": -0.01, "advanced": 0.0, "expert": 0.03}  # сложнее — меньше конкурентов
PAYMENT_SHIFT = {"capex": 0.0, "installment": 0.01, "opex": 0.025}  # рассрочка/сервис ценнее
BUDGET_SHARE = {"social": 1.0, "office": 0.4, "residential": 0.1, "hospitality": 0.15,
                "retail": 0.05, "warehouse": 0.05, "industrial": 0.05, "agro": 0.1}


def _fmt_int(value: float) -> str:
    return f"{int(value):,}".replace(",", " ")


def generate_deals(n: int, seed: int, projects: list[dict], positions: list[dict],
                   zones: dict[str, float]) -> list[dict]:
    rnd = random.Random(seed)
    catalog = {p["code"]: CatalogItem(p["code"], p["name"], p["system_group"],
                                      p["price_typical"], p["complexity_coef"])
               for p in positions}
    weights = {}
    for p in projects:
        weights[p["object_type"]] = weights.get(p["object_type"], 0) + 1
    types = list(OBJECT_TYPES)
    type_w = [weights.get(t, 0) + 2 for t in types]
    deals = []
    for _ in range(n):
        object_type = rnd.choices(types, type_w)[0]
        lo, hi = AREA_RANGE[object_type]
        area = round(math.exp(rnd.uniform(math.log(lo), math.log(hi))), -1)
        systems = list(OBJECT_TYPES[object_type]["systems"])
        if len(systems) > 3 and rnd.random() < 0.3:
            systems.remove(rnd.choice(systems[1:]))
        items = [LineInput(li.code, max(1, round(li.qty * rnd.uniform(0.8, 1.25))))
                 for li in suggest_items(object_type, area, systems)]
        level = rnd.choices(["basic", "advanced", "expert"], [0.35, 0.45, 0.20])[0]
        if rnd.random() < 0.85:
            region_code, city = ROSTOV["code"], rnd.choice(CITIES_ROSTOV)
            k_region = zones["ZONE-S"]
        else:
            region_code, city = rnd.choice(OTHER_ZONES)
            k_region = zones[region_code]
        norm = 1 + sum(li.qty for li in items) / 100
        duration = round(norm * rnd.choice([0.7, 1.0, 1.0, 1.2, 1.5]), 1)
        unique = rnd.random() < 0.08
        cost = calculate_cost(CostInput(items, level, k_region, city, duration, unique),
                              catalog, PricingConfig()).total
        shift = TYPE_SHIFT[object_type]
        budget = rnd.random() < BUDGET_SHARE[object_type]
        payment = rnd.choices(["capex", "installment", "opex"], [0.6, 0.25, 0.15])[0]
        market = (shift + LEVEL_SHIFT[level] + PAYMENT_SHIFT[payment]
                  + (BUDGET_SHIFT if budget else 0.0))
        index = min(max(rnd.gauss(1.36 + shift, 0.08), 1.10), 1.75)
        p_win = 1 / (1 + math.exp(STEEPNESS * (index - I50 - market)))
        won = rnd.random() < p_win
        closed = date(2023, 1, 15) + timedelta(days=rnd.randint(0, 1350))
        deals.append({
            "title": f"Диспетчеризация: {OBJECT_TYPES[object_type]['label']}, "
                     f"{_fmt_int(area)} м², {city}",
            "project_type": "dispatching",
            "object_type": object_type,
            "scale": "small" if area < 2000 else "medium" if area < 8000 else "large",
            "area_m2": area,
            "project_level": level,
            "region_code": region_code,
            "industry_code": INDUSTRY_BY_OBJECT[object_type],
            "cost_value": round(cost, 2),
            "contract_value": round(cost * index, -2),
            "outcome": "won" if won else "lost",
            "retro_price_basis": "synthetic",
            "financing_scheme": "budget" if budget
            else rnd.choices(["own", "lease"], [0.85, 0.15])[0],
            "payment_scheme": payment,
            "closed_at": closed.isoformat(),
            "scope": {"features": systems, "items": [{"code": li.code, "qty": li.qty}
                                                     for li in items],
                      "duration_months": duration, "has_unique_solution": unique,
                      "city": city},
        })
    return deals


def build(xlsx: Path, n_deals: int, seed: int) -> dict:
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    regions, coefficients = read_zones(wb)
    positions = read_positions(wb)
    projects, _companies = read_projects(wb)
    zones = {c["region_code"]: c["coefficient"] for c in coefficients}
    deals = generate_deals(n_deals, seed, projects, positions, zones)
    return {
        "_meta": {
            "generated_by": "infra/scripts/import_case_xlsx.py",
            "source_file": str(xlsx.relative_to(ROOT)),
            "seed": seed,
            "notice": "Справочники и регионы — из данных кейса. "
                      "historical_deals — синтетика (retro_price_basis=synthetic): "
                      "реальной истории сделок в кейсе нет.",
        },
        "regions": regions,
        "coefficients": coefficients,
        "positions": positions,
        "dictionaries": read_dictionaries(wb),
        "historical_deals": deals,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--xlsx", type=Path, default=XLSX)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--deals", type=int, default=400)
    parser.add_argument("--seed", type=int, default=20261024)
    args = parser.parse_args()
    bundle = build(args.xlsx, args.deals, args.seed)
    args.out.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    won = sum(d["outcome"] == "won" for d in bundle["historical_deals"])
    print(f"{args.out.relative_to(ROOT)}: регионов {len(bundle['regions'])}, "
          f"позиций {len(bundle['positions'])}, сделок {len(bundle['historical_deals'])} "
          f"(выиграно {won})")


if __name__ == "__main__":
    main()
