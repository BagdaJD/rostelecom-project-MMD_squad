"""Себестоимость проекта диспетчеризации «снизу вверх» по справочникам кейса (МОД3_Таб1–4).

Чистые функции без БД: каталог и параметры передаются аргументами, поэтому расчёт
воспроизводим и покрыт тестами. Что взято из кейса, а что является допущением, отмечено
у каждого параметра — это же видно пользователю в поле ``source`` у поправок.

Формула (режим по умолчанию ``complexity_mode="works"``)::

    E = Σ qᵢ·pᵢ                                    оборудование, Таб4
    W = Σ qᵢ·pᵢ·kᵢ × (ПИР 10% + ПНР 15% + шеф 5%)  работы, Таб3; kᵢ — сложность группы, Таб4
    C = (E + W·k_уровня) · k_региона · k_срочности · k_уникальности + ПО + резерв
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

# --- Источники параметров: показываются в UI рядом с каждой поправкой ---------------------
SOURCE_CASE = "кейс"
SOURCE_ASSUMPTION = "допущение"

ComplexityMode = Literal["works", "installation", "equipment"]
#: Как трактовать коэффициент сложности группы (кейс этого не уточняет, вопрос куратору):
#: works        — умножает базу работ (ПИР/ПНР/шеф-монтаж);
#: installation — (k − 1) × оборудование = отдельная статья «монтаж» (в Таб3 монтажа нет);
#: equipment    — умножает цену оборудования, работы считаются от неё.
COMPLEXITY_MODES: tuple[str, ...] = ("works", "installation", "equipment")


@dataclass(frozen=True)
class CatalogItem:
    code: str
    name: str
    group: str
    base_price: float
    complexity: float = 1.0
    unit: str = "шт."


@dataclass(frozen=True)
class PricingConfig:
    """Параметры расчёта. Значения по умолчанию = справочники кейса + явные допущения."""

    # МОД3_Таб3: доли работ от стоимости оборудования (кейс).
    work_shares: dict[str, float] = field(
        default_factory=lambda: {"design": 0.10, "commissioning": 0.15, "supervision": 0.05}
    )
    # МОД3_Таб2: уровень проекта (кейс).
    level_coefficients: dict[str, float] = field(
        default_factory=lambda: {"basic": 1.0, "advanced": 1.3, "expert": 1.6}
    )
    complexity_mode: ComplexityMode = "works"  # допущение
    level_applies_to: Literal["works", "total"] = "works"  # допущение
    region_applies_to: Literal["works", "total"] = "total"  # допущение: в Таб1 — логистика

    # Срочность (допущение): норма = base + per_100 × точек/100 мес.;
    # если клиент хочет быстрее, k = 1 + slope × (1 − t/норма), не выше max.
    norm_base_months: float = 1.0
    norm_months_per_100_points: float = 1.0
    urgency_slope: float = 0.5
    urgency_max: float = 1.3

    unique_solution_coefficient: float = 1.15  # допущение (диапазон 1,1–1,3)
    nonstandard_reserve_share: float = 0.20  # допущение: резерв на нестандартные позиции


@dataclass(frozen=True)
class LineInput:
    code: str
    qty: float


@dataclass(frozen=True)
class CustomLine:
    """Позиция вне каталога: нестандартное оборудование или ПО (на неё начисляется резерв)."""

    name: str
    qty: float
    unit_price: float
    kind: Literal["equipment", "software"] = "equipment"
    nonstandard: bool = True


@dataclass(frozen=True)
class CostInput:
    items: list[LineInput]
    project_level: str = "basic"
    regional_coefficient: float = 1.0
    region_label: str | None = None
    duration_months: float | None = None
    has_unique_solution: bool = False
    custom_lines: list[CustomLine] = field(default_factory=list)


@dataclass
class Factor:
    factor: str
    value: float
    note: str
    source: str


@dataclass
class CostResult:
    total: float
    #: Статьи себестоимости с уже применёнными коэффициентами; сумма = total.
    breakdown: dict[str, float]
    factors: list[Factor]
    points: float
    norm_months: float
    lines: list[dict]
    warnings: list[str] = field(default_factory=list)


ARTICLE_LABELS = {
    "equipment": "Оборудование",
    "installation": "Монтаж",
    "design": "Проектирование (ПИР)",
    "commissioning": "Пусконаладка (ПНР)",
    "supervision": "Шеф-монтаж",
    "software": "ПО",
    "reserve": "Резерв на нестандарт",
}


def norm_duration(points: float, config: PricingConfig) -> float:
    return config.norm_base_months + config.norm_months_per_100_points * points / 100


def urgency_coefficient(duration_months: float | None, points: float,
                        config: PricingConfig) -> float:
    """1.0 при нормальном или более длинном сроке; растёт, если срок сжат."""
    if not duration_months or duration_months <= 0:
        return 1.0
    norm = norm_duration(points, config)
    if duration_months >= norm:
        return 1.0
    value = 1 + config.urgency_slope * (1 - duration_months / norm)
    return round(min(value, config.urgency_max), 4)


def calculate_cost(query: CostInput, catalog: dict[str, CatalogItem],
                   config: PricingConfig | None = None) -> CostResult:
    config = config or PricingConfig()
    if config.complexity_mode not in COMPLEXITY_MODES:
        raise ValueError(f"неизвестный complexity_mode: {config.complexity_mode}")
    if query.project_level not in config.level_coefficients:
        raise ValueError(f"неизвестный уровень проекта: {query.project_level}")

    warnings: list[str] = []
    lines: list[dict] = []
    equipment_raw = 0.0  # Σ q·p
    equipment_weighted = 0.0  # Σ q·p·k
    for line in query.items:
        if line.qty <= 0:
            continue
        item = catalog.get(line.code)
        if item is None:
            warnings.append(f"Позиция {line.code} не найдена в каталоге и не учтена")
            continue
        amount = line.qty * item.base_price
        equipment_raw += amount
        equipment_weighted += amount * item.complexity
        lines.append({"code": item.code, "name": item.name, "group": item.group,
                      "qty": line.qty, "unit": item.unit, "unit_price": item.base_price,
                      "amount": amount, "complexity": item.complexity})

    custom_equipment = sum(c.qty * c.unit_price for c in query.custom_lines
                           if c.kind == "equipment")
    software = sum(c.qty * c.unit_price for c in query.custom_lines if c.kind == "software")
    nonstandard = sum(c.qty * c.unit_price for c in query.custom_lines if c.nonstandard)
    for c in query.custom_lines:
        lines.append({"code": None, "name": c.name, "group": "Нестандарт" if c.nonstandard
                      else "Прочее", "qty": c.qty, "unit": "шт.", "unit_price": c.unit_price,
                      "amount": c.qty * c.unit_price, "complexity": 1.0, "kind": c.kind})

    # --- база оборудования и работ по выбранной трактовке сложности ---
    installation = 0.0
    if config.complexity_mode == "works":
        equipment = equipment_raw
        works_base = equipment_weighted
    elif config.complexity_mode == "installation":
        equipment = equipment_raw
        works_base = equipment_raw
        installation = equipment_weighted - equipment_raw
    else:  # equipment
        equipment = equipment_weighted
        works_base = equipment_weighted
    equipment += custom_equipment
    works_base += custom_equipment  # нестандартное оборудование тоже проектируют и налаживают

    works = {name: works_base * share for name, share in config.work_shares.items()}

    k_level = config.level_coefficients[query.project_level]
    k_region = query.regional_coefficient or 1.0
    points = sum(line.qty for line in query.items if line.qty > 0) + sum(
        c.qty for c in query.custom_lines if c.kind == "equipment")
    k_urgency = urgency_coefficient(query.duration_months, points, config)
    k_unique = config.unique_solution_coefficient if query.has_unique_solution else 1.0

    # Уровень проекта.
    if config.level_applies_to == "works":
        # Уровень (мониторинг / управление / авторегулирование) — это программирование и
        # наладка, а не физический монтаж: статья «монтаж» уровнем не умножается.
        works = {k: v * k_level for k, v in works.items()}
    else:
        equipment *= k_level
        works = {k: v * k_level for k, v in works.items()}
        installation *= k_level

    # Регион.
    if config.region_applies_to == "total":
        equipment *= k_region
        installation *= k_region
        works = {k: v * k_region for k, v in works.items()}
    else:
        installation *= k_region
        works = {k: v * k_region for k, v in works.items()}

    # Срочность и уникальность — на всю проектную часть.
    k_project = k_urgency * k_unique
    breakdown = {"equipment": equipment * k_project}
    if installation:
        breakdown["installation"] = installation * k_project
    for name, value in works.items():
        breakdown[name] = value * k_project
    if software:
        breakdown["software"] = software
    reserve = nonstandard * config.nonstandard_reserve_share
    if reserve:
        breakdown["reserve"] = reserve
        warnings.append("Есть нестандартные позиции: цена требует подтверждения пресейлом")

    total = sum(breakdown.values())
    factors = [
        Factor("project_level", k_level, f"уровень проекта «{query.project_level}»",
               SOURCE_CASE),
        Factor("regional_coefficient", k_region,
               f"регион {query.region_label}" if query.region_label else "регион", SOURCE_CASE),
        Factor("urgency", k_urgency,
               f"срок {query.duration_months or '—'} мес. при норме "
               f"{norm_duration(points, config):.1f} мес.", SOURCE_ASSUMPTION),
        Factor("unique_solution", k_unique,
               "уникальное решение" if query.has_unique_solution else "типовое решение",
               SOURCE_ASSUMPTION),
        Factor("complexity_mode", 1.0, f"трактовка сложности: {config.complexity_mode}",
               SOURCE_ASSUMPTION),
    ]
    if not lines:
        warnings.append("Состав пуст: себестоимость не рассчитана")
    return CostResult(
        total=round(total, 2),
        breakdown={k: round(v, 2) for k, v in breakdown.items()},
        factors=factors,
        points=points,
        norm_months=round(norm_duration(points, config), 2),
        lines=lines,
        warnings=warnings,
    )


# --- Автоподбор состава по типу объекта и площади ------------------------------------------
# Нормативы — экспертное допущение для демо (не из кейса): (код, на объект, на 1000 м²).
SYSTEM_TEMPLATES: dict[str, list[tuple[str, float, float]]] = {
    "Электроснабжение": [("el_01", 2, 2.0), ("el_02", 1, 0.2), ("el_03", 1, 0.0)],
    "Отопление": [("ht_01", 1, 0.0), ("ht_02", 2, 1.5), ("ht_03", 1, 0.3)],
    "Водоснабжение": [("ws_01", 1, 0.3), ("ws_02", 1, 0.3), ("ws_03", 2, 2.0)],
    "Водоотведение": [("wo_01", 1, 0.2), ("wo_02", 1, 0.0), ("wo_03", 1, 0.0)],
    "Вентиляция": [("vn_01", 1, 0.5), ("vn_02", 1, 1.2), ("vn_03", 1, 0.5)],
    "Кондиционирование": [("kd_01", 1, 0.0), ("kd_02", 2, 2.0), ("kd_03", 0, 1.0)],
    "Газоснабжение": [("gs_01", 1, 0.3), ("gs_02", 1, 0.0)],
}

OBJECT_TYPES: dict[str, dict] = {
    "retail": {"label": "Торговый объект", "systems": [
        "Электроснабжение", "Отопление", "Водоснабжение", "Вентиляция", "Кондиционирование"]},
    "warehouse": {"label": "Склад / логистика", "systems": [
        "Электроснабжение", "Отопление", "Водоснабжение", "Водоотведение", "Вентиляция"]},
    "office": {"label": "Офис / администрация", "systems": [
        "Электроснабжение", "Отопление", "Водоснабжение", "Вентиляция", "Кондиционирование"]},
    "industrial": {"label": "Производство", "systems": [
        "Электроснабжение", "Отопление", "Водоснабжение", "Водоотведение", "Вентиляция",
        "Газоснабжение"]},
    "agro": {"label": "АПК", "systems": [
        "Электроснабжение", "Отопление", "Водоснабжение", "Водоотведение", "Вентиляция",
        "Газоснабжение"]},
    "residential": {"label": "Жилой дом (МКД)", "systems": [
        "Электроснабжение", "Отопление", "Водоснабжение", "Водоотведение"]},
    "social": {"label": "Соцобъект (школа, больница)", "systems": [
        "Электроснабжение", "Отопление", "Водоснабжение", "Вентиляция"]},
    "hospitality": {"label": "Отдых и спорт", "systems": [
        "Электроснабжение", "Отопление", "Водоснабжение", "Водоотведение",
        "Кондиционирование"]},
}


def suggest_items(object_type: str, area_m2: float,
                  systems: list[str] | None = None) -> list[LineInput]:
    """Типовой состав по нормативам: менеджер правит количества в форме."""
    spec = OBJECT_TYPES.get(object_type)
    chosen = systems or (spec["systems"] if spec else list(SYSTEM_TEMPLATES))
    area_k = max(area_m2, 0) / 1000
    result: list[LineInput] = []
    for system in chosen:
        for code, fixed, per_1000 in SYSTEM_TEMPLATES.get(system, []):
            qty = math.ceil(fixed + per_1000 * area_k)
            if qty > 0:
                result.append(LineInput(code, qty))
    return result


# --- Тип объекта по названию инвестпроекта (черновик расчёта из навигатора) ----------------
# Порядок важен: первое совпадение побеждает («торгово-складской» → склад).
_OBJECT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("residential", ("многоквартир", "жилого дома", "жилой дом", "жилого комплекса", "жк",
                     "комплексное развитие")),
    ("social", ("медицин", "медскан", "больниц", "поликлин", "школ", "детск")),
    ("warehouse", ("склад", "логист", "порт", "хранени")),
    ("agro", ("сельскохоз", "теплич", "комбикорм", "рыб", "осетр", "рак", "сад", "сада",
              "орех", "фундук", "картофел", "капуст", "аквакульт", "виноград", "агро")),
    ("industrial", ("завод", "производств", "цех", "технопарк", "мастерск", "ремонт",
                    "карьер", "дробильн", "спг")),
    ("retail", ("торгов", "магазин", "маркет", "потребительского рынка", "дорожного сервиса")),
    ("hospitality", ("отдых", "пляж", "стадион", "спорт", "картодром", "физкультур", "оздоров",
                     "кемпинг", "развлекат", "бассейн", "фитнес", "кафе", "столов", "питания",
                     "творческ")),
    ("office", ("административ", "делового управления", "офис")),
]

#: Ориентировочная стоимость строительства, ₽/м² — чтобы оценить площадь по бюджету проекта,
#: когда площади нет в описании. Допущение, в UI помечается «площадь оценена».
BUILD_COST_PER_M2 = {"retail": 50_000, "warehouse": 30_000, "office": 60_000,
                     "industrial": 40_000, "agro": 20_000, "residential": 70_000,
                     "social": 80_000, "hospitality": 60_000}


def guess_object_type(title: str | None) -> str:
    """Метки ищутся с начала слова: иначе «порт» находится в «спорт», а «рак» — в «каркас»."""
    import re

    text = f" {(title or '').lower()} "
    for object_type, markers in _OBJECT_RULES:
        if any(re.search(r"(?<![а-яёa-z])" + re.escape(m.strip()), text) for m in markers):
            return object_type
    return "office"


def parse_area_m2(text: str | None) -> float | None:
    """Площадь из описания: «площадью 538 кв.м.», «642,6 кв.м», «1 200 м²»."""
    import re

    if not text:
        return None
    m = re.search(r"(\d[\d\s]*(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м²|м2)", text.lower())
    if not m:
        return None
    try:
        return float(m.group(1).replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def estimate_area_m2(object_type: str, budget_rub: float | None) -> float | None:
    if not budget_rub or budget_rub <= 0:
        return None
    area = budget_rub / BUILD_COST_PER_M2.get(object_type, 50_000)
    return float(min(max(round(area, -1), 200), 30_000))
