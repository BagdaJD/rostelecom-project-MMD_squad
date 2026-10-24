#!/usr/bin/env python3
"""Генератор демонстрационного набора данных.

Данные синтетические: они нужны, чтобы проверить конвейер и показать три модуля,
не используя реальные персональные и коммерческие сведения. Перед пилотом набор
заменяется легальными источниками (см. docs/data-sources.md).

Запуск из корня репозитория:
    python3 infra/scripts/make_demo_bundle.py
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 20261024
OUT = Path(__file__).resolve().parents[2] / "data" / "seed" / "demo_bundle.json"

REGIONS = [
    # Потенциал и присутствие намеренно контрастны: нужно наблюдаемое «белое пятно».
    # center — долгота/широта для слоя агрегатов на карте.
    ("RU-MOS", "Московская область", 43000.0, 0.06, 62.0, 34, (37.62, 55.75)),
    ("RU-SVE", "Свердловская область", 38000.0, 0.09, 55.0, 28, (60.60, 56.84)),
    ("RU-TYU", "Тюменская область", 27000.0, 0.21, 12.0, 4, (65.53, 57.15)),
    ("RU-KRS", "Краснодарский край", 24000.0, 0.18, 17.0, 7, (38.98, 45.04)),
]

INDUSTRIES = [
    ("TEK", "Нефтегазовый сектор", "ТЭК", ["06.10", "19.20", "09.10"]),
    ("TRADE", "Розничная торговля", "Торговля", ["47.11", "47.52", "47.91"]),
    ("APK", "Пищевая промышленность", "АПК", ["01.11", "10.80", "10.41"]),
    ("IT", "Разработка ПО и данные", "ИТ", ["62.01", "63.11", "58.29"]),
    ("HEALTH", "Медицинские организации", "Здравоохранение", ["86.10", "86.90"]),
    ("TRANSPORT", "Логистика и транспорт", "Транспорт", ["49.20", "52.24", "52.29"]),
]

NAMES = {
    "TEK": ["Сибнефтемаш", "Уралгазстрой", "Югра-Терминал", "Каспий-Ойл"],
    "TRADE": ["Продовольственный дом", "Торговый квартал", "Магнит-Регион", "Сельпо"],
    "APK": ["Агрокомплекс Нива", "Молочный комбинат Заря", "Масложировой комбинат", "Зерно-Плюс"],
    "IT": ["ДатаЛаб", "Интегратор АИС", "СофтРешения", "ЦОД-Эксплуатация"],
    "HEALTH": ["Клиника Медуница", "Городская больница №4", "Лаборатория Гелиос", "Дентал-Сервис"],
    "TRANSPORT": ["ТрансЛогистик", "РегионКарго", "Порт-Терминал", "Экспресс-Доставка"],
}

PROJECTS = [
    # (заголовок, отрасль, регион, стадия, описание)
    ("Строительство теплично-овощного комплекса «Нива-Агро»", "APK", "RU-TYU", "design",
     "Проектирование тепличного комплекса 24 га с автоматизированной системой управления микроклиматом, "
     "диспетчеризацией и каналом связи для передачи данных АСУ ТП."),
    ("Модернизация нефтеперекачивающей станции «Урал-12»", "TEK", "RU-SVE", "modernization",
     "Модернизация узла учёта и АСУ ТП, организация выделенного канала связи между КПП и ЦДУ, "
     "промышленная информационная безопасность."),
    ("Реконструкция логистического хаба «Восточный»", "TRANSPORT", "RU-SVE", "construction",
     "Строительство складского комплекса класса А, видеонаблюдение по периметру, серверная и СХД, "
     "каналы передачи данных для весового контроля."),
    ("Ввод в эксплуатацию многопрофильного медицинского центра", "HEALTH", "RU-MOS", "launch",
     "Медицинская информационная система, защищённый канал доступа к ЕГИСЗ, видеонаблюдение, "
     "средства защиты информации и резервирование канала связи."),
    ("Проектирование сети автоматизированных АЗС", "TEK", "RU-KRS", "design",
     "Диспетчеризация 40 объектов, облачная платформа мониторинга, каналы связи на каждом объекте."),
    ("Строительство распределительного центра розничной сети", "TRADE", "RU-KRS", "construction",
     "Серверное оборудование, WMS, видеонаблюдение и резервный канал передачи данных."),
]

TENDERS = [
    ("0118200001126000145", "Поставка серверного оборудования для Логистического хаба", 18_400_000,
     "TRANSPORT", "construction", "RU-SVE", "equipment_server"),
    ("0118300002226000087", "Работы по монтажу структурированной кабельной сети", 7_250_000,
     "APK", "design", "RU-TYU", "works_cabling"),
    ("0116200003326000203", "Поставка системы видеонаблюдения, 128 камер", 12_900_000,
     "TRANSPORT", "construction", "RU-SVE", "equipment_video"),
    ("0120100004426000011", "Услуги промышленной информационной безопасности", 5_600_000,
     "TEK", "modernization", "RU-SVE", "software_security"),
    ("0123300005526000042", "Организация защищённого канала связи медицинского центра", 3_150_000,
     "HEALTH", "launch", "RU-MOS", "works_cabling"),
    ("0123600006626000099", "Поставка АСУ ТП тепличного комплекса", 24_800_000,
     "APK", "design", "RU-TYU", "equipment_asutp"),
]

DEALS = [
    ("Канал связи и серверная для склада 42 тыс. м²", "connectivity", "large", "RU-SVE", "TRANSPORT", 41_500_000),
    ("Видеонаблюдение логистического терминала", "video_surveillance", "medium", "RU-MOS", "TRANSPORT", 16_800_000),
    ("АСУ ТП молочного комбината", "iot_asu_tp", "medium", "RU-TYU", "APK", 33_200_000),
    ("Защищённый канал для сети клиник", "connectivity", "medium", "RU-MOS", "HEALTH", 12_400_000),
    ("Серверная и СХД для розничной сети", "it_infrastructure", "large", "RU-SVE", "TRADE", 28_900_000),
    ("Диспетчеризация 35 АЗС", "iot_asu_tp", "small", "RU-KRS", "TEK", 9_700_000),
    ("Комплексная ИБ для нефтебазы", "information_security", "medium", "RU-SVE", "TEK", 14_300_000),
    ("Облачная платформа мониторинга для агрохолдинга", "it_infrastructure", "small", "RU-TYU", "APK", 8_100_000),
    ("Канал связи и Wi-Fi для ТРК", "connectivity", "small", "RU-KRS", "TRADE", 6_400_000),
    ("ЦОД для региональной сети клиник", "it_infrastructure", "large", "RU-MOS", "HEALTH", 52_000_000),
]

POSITIONS = [
    ("Сервер 2U, 2×Xeon, 256 ГБ", "equipment", "шт", 380_000, 620_000, 480_000),
    ("СХД 100 ТБ", "equipment", "шт", 1_100_000, 1_900_000, 1_450_000),
    ("IP-камера 4 Мп уличная", "equipment", "шт", 9_500, 21_000, 14_000),
    ("Коммутатор уровня ядра", "equipment", "шт", 240_000, 520_000, 360_000),
    ("Контроллер АСУ ТП (ПЛК)", "equipment", "шт", 145_000, 390_000, 240_000),
    ("Лицензия гипервизора", "software", "сокет", 22_000, 48_000, 34_000),
    ("СИЕМ-платформа, подписка", "software", "год", 480_000, 1_200_000, 780_000),
    ("СМР: СКС, за метр рабочего места", "works", "раб. место", 3_800, 9_200, 6_100),
    ("СМР: прокладка ВОЛС", "works", "км", 145_000, 380_000, 240_000),
    ("Пусконаладка АСУ ТП", "works", "объект", 320_000, 890_000, 560_000),
]


def inn(digits9: str) -> str:
    """Контрольная цифра ИНН-10, чтобы матчинг по ИНН реально срабатывал в демо."""
    weights = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    control = sum(w * int(d) for w, d in zip(weights, digits9)) % 11 % 10
    return digits9 + str(control)


def main() -> None:
    rng = random.Random(SEED)
    today = date(2026, 10, 1)

    regions = [
        {"code": code, "name": name, "center": [center[0], center[1]]}
        for code, name, *_, center in REGIONS
    ]

    industries = [
        {"code": code, "name": name, "group": group, "okved": okved}
        for code, name, group, okved in INDUSTRIES
    ]

    companies = []
    counter = 0
    for region_code, region_name, _, growth, _, _, _center in REGIONS:
        for ind_code, ind_name, group, okved in INDUSTRIES:
            # 2–3 компании на срез: карта и «белые пятна» считаются на живых данных.
            for name in rng.sample(NAMES[ind_code], k=2):
                counter += 1
                base = float(rng.uniform(300, 4200))
                # Динамика сильнее в регионах-кандидатах на «белое пятно».
                boost = 1.0 + (growth - 0.06)
                suffix = "" if region_code in ("RU-MOS", "RU-SVE") else " (филиал)"
                companies.append(
                    {
                        "source": "demo",
                        "external_id": f"DEMO-{counter:04d}",
                        "name": f"{name} {region_code.split('-')[1]}{suffix}",
                        "inn": inn(f"{'77' if region_code == 'RU-MOS' else '66'}{counter:07d}"[:9]),
                        "ogrn": None,
                        "industry_code": okved[0],
                        "region_code": region_code,
                        "employee_count": rng.randint(40, 900),
                        "revenue": {
                            "2023": round(base, 1),
                            "2024": round(base * (1 + 0.04 * boost + rng.uniform(-0.02, 0.03)), 1),
                            "2025": round(base * (1 + 0.07 * boost + rng.uniform(-0.02, 0.05)), 1),
                        },
                        "source_url": "https://example.com/demo",
                        "license_note": "синтетические данные, созданы для демонстрации",
                    }
                )

    projects = []
    for title, ind, region, stage, description in PROJECTS:
        start = today + timedelta(days=rng.randint(-240, 320))
        projects.append(
            {
                "source": "demo_investregistry",
                "external_id": f"IP-{abs(hash(title)) % 10000:04d}",
                "title": title,
                "description": description,
                "stage": stage,
                "planned_start": start.isoformat(),
                "planned_end": (start + timedelta(days=rng.randint(300, 900))).isoformat(),
                "estimated_budget": rng.randint(30, 900) * 1_000_000,
                "region_code": region,
                "industry_code": next(o for c, _, _, o in INDUSTRIES if c == ind)[0],
                "confidence": 0.8,
                "source_url": "https://example.com/invest",
            }
        )

    tenders = []
    for external_id, title, price, ind, stage, region, work in TENDERS:
        published = today - timedelta(days=rng.randint(5, 90))
        tenders.append(
            {
                "source": "demo_eis",
                "external_id": external_id,
                "title": title,
                "description": f"Закупка в рамках проекта: {work}",
                "price": price,
                "publication_date": published.isoformat(),
                "deadline_date": (published + timedelta(days=rng.randint(20, 60))).isoformat(),
                "category": work,
                "source_url": f"https://example.com/eis/{external_id}",
                "customer_key": f"inn:{next((c['inn'] for c in companies if c['region_code'] == region), '')}",
                "project_title": next(
                    (p["title"] for p in projects if p["region_code"] == region and p["stage"] == stage),
                    None,
                ),
                "link_method": "inn_keyword",
                "link_confidence": 0.7,
            }
        )

    presence = []
    for region_code, _, _, _, coverage, contracts, _center in REGIONS:
        for service, share in (("connectivity", 1.0), ("it_infrastructure", 0.7), ("video_surveillance", 0.5)):
            presence.append(
                {
                    "region_code": region_code,
                    "service_type": service,
                    "coverage_percent": round(coverage * share, 1),
                    "contracts_count": max(int(contracts * share), 0),
                    "as_of_date": "2026-09-01",
                }
            )

    coefficients = [
        {"region_code": code, "work_type": "works", "coefficient": coef, "effective_from": "2026-01-01"}
        for (code, *_rest), coef in zip(REGIONS, (1.00, 1.05, 1.08, 1.07))
    ]

    positions = [
        {
            "name": name,
            "category": cat,
            "unit": unit,
            "price_min": p_min,
            "price_max": p_max,
            "price_typical": p_typ,
            "price_period": "2026",
        }
        for name, cat, unit, p_min, p_max, p_typ in POSITIONS
    ]

    deals = []
    for title, ptype, scale, region, industry, value in DEALS:
        deals.append(
            {
                "title": title,
                "project_type": ptype,
                "scale": scale,
                "region_code": region,
                "industry_code": industry,
                "contract_value": value,
                # Все цены синтетические: калькулятор обязан показывать предупреждение.
                "retro_price_basis": "synthetic",
                "financing_scheme": "own",
                "closed_at": (today - timedelta(days=rng.randint(120, 900))).isoformat(),
                "scope": {"features": [f"works_{ptype}", "oborudovanie_server"]},
            }
        )

    bundle = {
        "_meta": {
            "generated_by": "infra/scripts/make_demo_bundle.py",
            "seed": SEED,
            "notice": "Данные синтетические. Не являются данными ФНС, ЕИС или ПАО «Ростелеком».",
        },
        "regions": regions,
        "industries": industries,
        "companies": companies,
        "projects": projects,
        "tenders": tenders,
        "presence": presence,
        "coefficients": coefficients,
        "positions": positions,
        "historical_deals": deals,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {k: len(v) for k, v in bundle.items() if isinstance(v, list)}
    print(f"записано: {OUT}")
    print("объекты:", counts)


if __name__ == "__main__":
    main()
