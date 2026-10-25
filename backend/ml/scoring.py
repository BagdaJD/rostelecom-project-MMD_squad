"""Скоринг потенциала и «белые пятна».

Реализация — детерминированная эвристика с явными весами (режим `heuristic`), а не
«магическая» модель: веса конфигурируемы, вклады признаков возвращаются в API, и
результат сравнивается с базовой линией «среднее по отрасли и региону» (ТЗ 7, 8.1).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

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
    revenue_sum: float | None = None
    revenue_sum_max: float = 0.0
    growth_share: float | None = None
    companies_count: int = 0
    companies_count_max: int = 0
    active_projects: int | None = None
    active_projects_max: int = 0
    open_tenders: int | None = None
    open_tenders_max: int = 0


@dataclass
class PotentialResult:
    score: float
    factors: list[Factor] = field(default_factory=list)
    scoring_mode: str = "heuristic"
    data_quality: str = "limited"
    available_features: dict[str, bool] = field(default_factory=dict)


def _ratio(value: float | None, total: float) -> float:
    if value is None or total <= 0 or value <= 0:
        return 0.0
    return min(max(value / total, 0.0), 1.0)


def score_potential(data: PotentialInput) -> PotentialResult:
    """Legacy API: нижняя оценка по фиксированным весам с флагами доступности."""
    raw = {
        "revenue_scale": _ratio(data.revenue_sum, data.revenue_sum_max),
        # Рост нормализуем так, чтобы +20 % давало 1.0 — типичный верх для отраслей.
        "revenue_growth": min(max((data.growth_share or 0) / 0.20, 0.0), 1.0),
        "business_density": _ratio(data.companies_count, data.companies_count_max),
        "investment_activity": _ratio(data.active_projects, data.active_projects_max),
        "tender_activity": _ratio(data.open_tenders, data.open_tenders_max),
    }
    score = round(sum(WEIGHTS[k] * v for k, v in raw.items()) * 100, 1)
    factors = [
        Factor(code=k, label=k.replace("_", " "), contribution=round(WEIGHTS[k] * v * 100, 1))
        for k, v in sorted(raw.items(), key=lambda kv: -kv[1] * WEIGHTS[kv[0]])
    ]
    availability = {
        "revenue_scale": data.revenue_sum is not None,
        "revenue_growth": data.growth_share is not None,
        "business_density": data.companies_count > 0,
        "investment_activity": data.active_projects is not None,
        "tender_activity": data.open_tenders is not None,
    }
    return PotentialResult(
        score=score,
        factors=factors,
        available_features=availability,
        data_quality="sufficient" if all(availability.values()) else "limited",
    )


def priority_category(score: float) -> str:
    return "high" if score >= 66 else ("medium" if score >= 33 else "low")


def quartile_cut(values: list[float], quantile: float) -> float:
    """Линейная интерполяция квантиля; при малом объёме возвращает медиану."""
    if not 0 <= quantile <= 1:
        raise ValueError("Квантиль должен быть в [0, 1]")
    if any(not math.isfinite(v) for v in values):
        raise ValueError("Квантили требуют конечных значений")
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
    return (
        presence is not None
        and potential is not None
        and potential >= p_cut
        and presence <= presence_cut
    )


def load_scoring_config(path=None) -> dict:
    text = Path(path or Path(__file__).with_name("scoring_config.json")).read_text(encoding="utf-8")
    config = json.loads(text)
    for group in ("company_weights", "territory_weights"):
        weights = config[group]
        if any(not math.isfinite(v) or v < 0 for v in weights.values()) or not math.isclose(
            sum(weights.values()), 1.0, abs_tol=1e-9
        ):
            raise ValueError(f"Веса {group} должны быть неотрицательны и давать сумму 1")
    config["model_version"] = (
        config["version"] + "-" + hashlib.sha256(text.encode()).hexdigest()[:8]
    )
    return config


def score_company(features: dict, *, as_of: date, config: dict | None = None) -> dict:
    config = config or load_scoring_config()
    weights = config["company_weights"]
    projects = features.get("confirmed_projects") or []
    relevance = config["industry_fit"].get(features.get("industry"))
    nlp_used = any(
        p.get("recommendations")
        and any(
            r.get("evidence_type") in ("explicit", "inferred")
            and r.get("rule_id") != "inferred:semantic"
            for r in p["recommendations"]
        )
        for p in projects
    )
    if nlp_used:
        relevance = max(relevance or 0, 0.8)
    employees = features.get("employee_count")
    size_basis = "employee_count" if employees is not None else "sme_category_proxy"
    size = (
        min(math.log1p(max(employees, 0)) / math.log1p(config["employee_cap"]), 1)
        if employees is not None
        else config["sme_size_proxy"].get(features.get("sme_category"))
    )
    budgets = [
        p["investment_mln_rub"]
        for p in projects
        if p.get("investment_mln_rub") is not None and p["investment_mln_rub"] >= 0
    ]
    investment = (
        min(math.log1p(sum(budgets)) / math.log1p(config["investment_cap_mln"]), 1)
        if budgets
        else (min(len(projects) / 5, 1) if projects else None)
    )
    # Год — только сигнал времени предложения, не доказательство стадии стройки.
    timing = []
    for project in projects:
        start, end = project.get("start_year"), project.get("end_year")
        if start is not None and end is not None and start <= end and end >= as_of.year:
            timing.append(1 / (1 + max(start - as_of.year, 0)))
    values = {
        "industry_fit": relevance,
        "company_size": size,
        "investment_activity": investment,
        "timeliness": max(timing) if timing else None,
    }
    coverage = sum(weights[k] for k, v in values.items() if v is not None)
    sufficient = (
        coverage >= config["minimum_coverage"] and sum(v is not None for v in values.values()) >= 2
    )
    factors = [
        {
            "code": key,
            "available": value is not None,
            "value": value,
            "weight": weights[key],
            "effective_weight": weights[key] / coverage if value is not None and coverage else 0,
            "contribution": round(value * weights[key] / coverage * 100, 4)
            if value is not None and sufficient
            else None,
        }
        for key, value in values.items()
    ]
    score = round(sum(f["contribution"] or 0 for f in factors), 2) if sufficient else None
    limitations = ["Экспертные веса; рейтинг не является вероятностью продажи"]
    if coverage < 1:
        limitations.append(
            "Веса перенормированы по доступным факторам; неполные профили несопоставимы с полными"
        )
    if not projects:
        limitations.append(
            "Нет подтверждённых связей с инвестиционными проектами; активность неизвестна"
        )
    if size_basis == "sme_category_proxy":
        limitations.append("Размер оценён по категории МСП; численность неизвестна")
    return {
        "score": score,
        "priority_category": priority_category(score) if score is not None else None,
        "factors": factors,
        "feature_coverage": round(coverage, 4),
        "data_quality": "insufficient"
        if not sufficient
        else ("sufficient" if coverage == 1 else "limited"),
        "scoring_mode": "heuristic",
        "model_version": config["model_version"],
        "as_of": as_of.isoformat(),
        "size_basis": size_basis,
        "nlp_influence": "industry_fit max 0.8; учтён один раз" if nlp_used else "none",
        "explanation": limitations,
    }


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
