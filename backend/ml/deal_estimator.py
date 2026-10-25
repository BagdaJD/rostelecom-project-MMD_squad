"""Оценка стоимости по аналогам (AI-функция C, ТЗ 8.3).

Без истории завершённых сделок это расчёт на аналогах и правилах, а не валидированный
прогноз — поэтому возвращаются аналоги, поправки, качество данных и предупреждение.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

URGENCY_COEFFICIENT = {"normal": 1.0, "high": 1.05, "critical": 1.12}
UNIQUE_SOLUTION_COEFFICIENT = 1.08


@dataclass
class Analog:
    deal_id: int
    title: str
    contract_value: float
    project_type: str
    scale: str | None
    region_id: int | None
    retro_price_basis: str = "synthetic"
    features: tuple[str, ...] = ()


@dataclass
class EstimateInput:
    project_type: str
    scale: str | None = None
    region_id: int | None = None
    works: list[str] = field(default_factory=list)
    equipment: list[str] = field(default_factory=list)
    software: list[str] = field(default_factory=list)
    urgency: str = "normal"
    financing_scheme: str | None = None
    has_unique_solution: bool = False
    regional_coefficient: float = 1.0


@dataclass
class EstimateResult:
    price_min: float
    price_optimum: float
    price_max: float
    comparables: list[dict]
    adjustments: list[dict]
    data_quality: str
    estimator_mode: str = "analogs"
    warning: str | None = None


def similarity(query: EstimateInput, analog: Analog) -> float:
    """Взвешенное сходство по типам и составу работ: масштабируемо и объяснимо."""
    score = 0.0
    score += 0.45 if query.project_type == analog.project_type else 0.0
    score += 0.15 if query.scale and query.scale == analog.scale else 0.0
    score += 0.10 if query.region_id and query.region_id == analog.region_id else 0.0

    wanted = set(query.works) | set(query.equipment) | set(query.software)
    have = set(analog.features)
    if wanted and have:
        score += 0.30 * (len(wanted & have) / len(wanted))
    return round(min(score, 1.0), 3)


def select_analogs(
    query: EstimateInput, pool: list[Analog], top_k: int = 5
) -> list[tuple[Analog, float]]:
    ranked = sorted(((a, similarity(query, a)) for a in pool), key=lambda x: -x[1])
    return [(a, s) for a, s in ranked[:top_k] if s > 0]


def estimate_deal(query: EstimateInput, pool: list[Analog], top_k: int = 5) -> EstimateResult:
    chosen = select_analogs(query, pool, top_k)
    if not chosen:
        return EstimateResult(
            price_min=0,
            price_optimum=0,
            price_max=0,
            comparables=[],
            adjustments=[],
            data_quality="insufficient",
            warning="Похожие проекты не найдены: диапазон не рассчитан, нужна ручная оценка",
        )

    values = [a.contract_value for a, _ in chosen]
    optimum = median(values)
    adjustments = [{"factor": "regional_coefficient", "value": query.regional_coefficient}]
    if query.urgency != "normal":
        adjustments.append({"factor": "urgency", "value": URGENCY_COEFFICIENT[query.urgency]})
    if query.has_unique_solution:
        adjustments.append({"factor": "unique_solution", "value": UNIQUE_SOLUTION_COEFFICIENT})

    coefficient = 1.0
    for adj in adjustments:
        coefficient *= float(adj["value"])

    spread = 0.25
    if len(values) >= 3 and optimum > 0:
        spread = min(max((max(values) - min(values)) / optimum / 2, 0.12), 0.45)

    adjusted = optimum * coefficient
    best_similarity = max(s for _, s in chosen)
    data_quality = "sufficient" if len(chosen) >= 3 and best_similarity >= 0.6 else "limited"
    warning = None
    if best_similarity < 0.5:
        warning = "Слабое сходство аналогов: диапазон ориентировочный, обязательна ручная проверка"
        data_quality = "limited"
    if all(a.retro_price_basis == "synthetic" for a, _ in chosen):
        warning = "Цены аналогов синтетические: расчёт демонстрационный, не рыночная оценка"

    return EstimateResult(
        price_min=round(adjusted * (1 - spread), 2),
        price_optimum=round(adjusted, 2),
        price_max=round(adjusted * (1 + spread), 2),
        comparables=[
            {
                "deal_id": a.deal_id,
                "title": a.title,
                "contract_value": a.contract_value,
                "similarity": s,
                "retro_price_basis": a.retro_price_basis,
            }
            for a, s in chosen
        ],
        adjustments=adjustments,
        data_quality=data_quality,
        warning=warning,
    )
