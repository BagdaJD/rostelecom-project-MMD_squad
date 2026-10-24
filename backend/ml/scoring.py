"""Скоринг потенциала и «белые пятна».

Реализация — детерминированная эвристика с явными весами (режим `heuristic`), а не
«магическая» модель: веса конфигурируемы, вклады признаков возвращаются в API, и
результат сравнивается с базовой линией «среднее по отрасли и региону» (ТЗ 7, 8.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas import Factor

# Веса зафиксированы здесь, а не разбросаны по коду: их показывает UI и можно оспорить.
WEIGHTS: dict[str, float] = {
    "revenue_scale": 0.30,
    "revenue_growth": 0.25,
    "business_density": 0.15,
    "investment_activity": 0.20,
    "tender_activity": 0.10,
}


@dataclass
class PotentialInput:
    revenue_sum: float = 0.0
    revenue_sum_max: float = 0.0
    growth_share: float = 0.0
    companies_count: int = 0
    companies_count_max: int = 0
    active_projects: int = 0
    active_projects_max: int = 0
    open_tenders: int = 0
    open_tenders_max: int = 0


@dataclass
class PotentialResult:
    score: float
    factors: list[Factor] = field(default_factory=list)
    scoring_mode: str = "heuristic"


def _ratio(value: float, total: float) -> float:
    if total <= 0 or value <= 0:
        return 0.0
    return min(max(value / total, 0.0), 1.0)


def score_potential(data: PotentialInput) -> PotentialResult:
    """0–100. Пропуск даёт вклад 0, а не среднее: честнее для карты."""
    raw = {
        "revenue_scale": _ratio(data.revenue_sum, data.revenue_sum_max),
        # Рост нормализуем так, чтобы +20 % давало 1.0 — типичный верх для отраслей.
        "revenue_growth": min(max(data.growth_share / 0.20, 0.0), 1.0),
        "business_density": _ratio(data.companies_count, data.companies_count_max),
        "investment_activity": _ratio(data.active_projects, data.active_projects_max),
        "tender_activity": _ratio(data.open_tenders, data.open_tenders_max),
    }
    score = round(sum(WEIGHTS[k] * v for k, v in raw.items()) * 100, 1)
    factors = [
        Factor(code=k, label=k.replace("_", " "), contribution=round(WEIGHTS[k] * v * 100, 1))
        for k, v in sorted(raw.items(), key=lambda kv: -kv[1] * WEIGHTS[kv[0]])
    ]
    return PotentialResult(score=score, factors=factors)


def priority_category(score: float) -> str:
    return "high" if score >= 66 else ("medium" if score >= 33 else "low")


def quartile_cut(values: list[float], quantile: float) -> float:
    """Линейная интерполяция квантиля; при малом объёме возвращает медиану."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * quantile
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def is_white_space(potential: float, presence: float, p_cut: float, presence_cut: float) -> bool:
    """Потенциал >= P75 и присутствие <= P25 — формальное определение из ТЗ 7."""
    return potential >= p_cut and presence <= presence_cut


def explain_white_space(
    *,
    companies_count: int,
    client_count: int,
    active_projects: int,
    revenue_yoy: float | None,
    coverage_percent: float | None,
) -> list[str]:
    """Объяснение метриками, а не цветом — требование кейса к «белым пятнам»."""
    lines: list[str] = []
    if revenue_yoy is not None:
        lines.append(f"Средняя динамика выручки {revenue_yoy:+.1f} % за последний год")
    lines.append(f"Компаний в срезе: {companies_count}, из них клиентов: {client_count}")
    if active_projects:
        lines.append(f"Активных инвестиционных проектов: {active_projects}")
    if coverage_percent is not None:
        lines.append(f"Покрытие услугами: {coverage_percent:.0f} %")
    else:
        lines.append("Покрытие услугами не подтверждено источником")
    lines.append("Расчёт выполнен экспертной эвристикой, не доказанной вероятностью сделки")
    return lines
