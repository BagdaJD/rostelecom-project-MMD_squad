"""Цена сделки калькулятора: вилка по аналогам и оптимум по ожидаемой прибыли.

Себестоимость считается по справочникам кейса (``ml/deal_cost.py``). Вилка строится как
себестоимость × наценка похожих сделок, оптимум — максимум ожидаемой прибыли
«(цена − себестоимость) × шанс выиграть».

Отдельный модуль калькулятора: прежняя оценка по аналогам (``ml/deal_estimator.py``)
не меняется. Без истории завершённых сделок это расчёт на аналогах и правилах, а не
валидированный прогноз — поэтому возвращаются аналоги, качество данных и предупреждения.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median


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
    # Для гибридного режима: себестоимость сделки, исход и площадь.
    cost_value: float | None = None
    outcome: str | None = None  # won | lost | None
    area_m2: float | None = None
    object_type: str | None = None


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
    area_m2: float | None = None
    object_type: str | None = None


def similarity(query: EstimateInput, analog: Analog) -> float:
    """Взвешенное сходство по типам и составу работ: масштабируемо и объяснимо."""
    score = 0.0
    if query.object_type and analog.object_type:
        # Внутри одного типа проекта (диспетчеризация) важен тип объекта: ТЦ ≠ офис.
        score += 0.30 if query.project_type == analog.project_type else 0.0
        score += 0.15 if query.object_type == analog.object_type else 0.0
    else:
        score += 0.45 if query.project_type == analog.project_type else 0.0
    if query.area_m2 and analog.area_m2:
        # Близость площади: одинаковая → 0.15, отличие в 3 раза и больше → 0.
        ratio = abs(math.log(query.area_m2 / analog.area_m2)) / math.log(3)
        score += 0.15 * max(0.0, 1 - ratio)
    else:
        score += 0.15 if query.scale and query.scale == analog.scale else 0.0
    score += 0.10 if query.region_id and query.region_id == analog.region_id else 0.0

    wanted = set(query.works) | set(query.equipment) | set(query.software)
    have = set(analog.features)
    if wanted and have:
        score += 0.30 * (len(wanted & have) / len(wanted))
    return round(min(score, 1.0), 3)


def select_analogs(query: EstimateInput, pool: list[Analog],
                   top_k: int = 5) -> list[tuple[Analog, float]]:
    ranked = sorted(((a, similarity(query, a)) for a in pool), key=lambda x: -x[1])
    return [(a, s) for a, s in ranked[:top_k] if s > 0]


@dataclass(frozen=True)
class PriceConfig:
    """Параметры вилки. Все — допущения для демо, настраиваются без правки формул."""

    margin_floor: float = 0.15  # минимальная маржа: ниже не продаём
    margin_target: float = 0.25  # для режима без аналогов
    margin_ceiling: float = 0.35
    top_k: int = 10
    min_indexed_analogs: int = 3
    min_outcomes_for_pwin: int = 30
    # Шанс выиграть оцениваем по своему сегменту рынка: N ближайших сделок, а не по всем —
    # у торговых объектов и госзаказчиков разная конкуренция.
    win_model_neighbors: int = 80
    curve_points: int = 41
    annual_rate: float = 0.20  # стоимость денег для рассрочки и сервиса
    installment_months: int = 12
    opex_months: int = 36
    opex_service_fee: float = 5000.0  # абонентская плата за обслуживание, ₽/мес


@dataclass
class WinModel:
    """Шанс выиграть как логистическая функция наценки: p = 1 / (1 + e^(a + b·наценка))."""

    a: float
    b: float
    n: int
    basis: str  # synthetic | contract | mixed

    def p(self, index: float) -> float:
        z = self.a + self.b * index
        if z > 50:
            return 0.0
        return 1 / (1 + math.exp(z))


@dataclass
class HybridResult:
    estimator_mode: str  # hybrid | rule_based
    cost_total: float
    price_min: float
    price_optimum: float
    price_max: float
    margin_min: float
    margin_optimum: float
    margin_max: float
    win_probability: float | None
    optimum_method: str
    index_stats: dict
    comparables: list[dict]
    curve: list[dict]
    data_quality: str
    win_model: dict | None
    warnings: list[str] = field(default_factory=list)


def weighted_quantile(values: list[float], weights: list[float], q: float) -> float:
    """Взвешенный квантиль с линейной интерполяцией по накопленному весу."""
    pairs = sorted(zip(values, weights, strict=True))
    total = sum(w for _, w in pairs)
    if total <= 0:
        return median(values)
    acc, points = 0.0, []
    for v, w in pairs:
        points.append(((acc + w / 2) / total, v))
        acc += w
    if q <= points[0][0]:
        return points[0][1]
    for (q0, v0), (q1, v1) in zip(points, points[1:], strict=False):
        if q <= q1:
            return v0 + (v1 - v0) * (q - q0) / (q1 - q0)
    return points[-1][1]


def fit_win_model(pool: list[Analog], min_outcomes: int = 30) -> WinModel | None:
    """Логистическая регрессия «наценка → выиграли» (scikit-learn, один признак).

    Запасная модель, когда для многофакторной (ml/win_model.py) мало сделок с исходом.
    Регуляризация почти выключена (C=1e4): коэффициенты — по данным, но не улетают в
    бесконечность, если исходы разделимы.
    """
    from sklearn.linear_model import LogisticRegression

    data = [(a.contract_value / a.cost_value, 1 if a.outcome == "won" else 0, a)
            for a in pool if a.cost_value and a.cost_value > 0 and a.outcome in ("won", "lost")]
    if len(data) < min_outcomes or len({y for _, y, _ in data}) < 2:
        return None
    clf = LogisticRegression(C=1e4, max_iter=1000)
    clf.fit([[x] for x, _, _ in data], [y for _, y, _ in data])
    c0, c1 = float(clf.intercept_[0]), float(clf.coef_[0][0])
    if c1 >= 0:  # дороже → чаще выигрываем: данные противоречат здравому смыслу
        return None
    bases = {a.retro_price_basis for _, _, a in data}
    basis = bases.pop() if len(bases) == 1 else "mixed"
    # P(выиграли) = sigmoid(c0 + c1·x) храним как p = 1 / (1 + e^(a + b·x)), a = −c0, b = −c1.
    return WinModel(a=-c0, b=-c1, n=len(data), basis=basis)


def local_win_model(query: EstimateInput, pool: list[Analog],
                    config: PriceConfig) -> WinModel | None:
    """Модель шанса по ближайшим сделкам; если их исходов мало — по всему пулу."""
    nearest = [a for a, _ in select_analogs(query, pool, config.win_model_neighbors)]
    return (fit_win_model(nearest, config.min_outcomes_for_pwin)
            or fit_win_model(pool, config.min_outcomes_for_pwin))


def _margin(price: float, cost: float) -> float:
    return (price - cost) / price if price > 0 else 0.0


def _probs(model, indices: list[float]) -> list[float]:
    """Шанс выиграть для набора наценок: пакетно, если модель это умеет (sklearn)."""
    if hasattr(model, "curve"):
        return model.curve(indices)
    return [model.p(i) for i in indices]


def estimate_hybrid(query: EstimateInput, pool: list[Analog], cost_total: float,
                    config: PriceConfig | None = None, win_model=None) -> HybridResult:
    """Вилка от себестоимости: минимум / оптимум / максимум + кривая для графика маржи.

    ``win_model`` — внешняя модель шанса выиграть (многофакторная, ml/win_model.py); если
    её нет, используется однофакторная логистика по ближайшим сделкам.
    """
    config = config or PriceConfig()
    if cost_total <= 0:
        raise ValueError("себестоимость должна быть больше нуля")
    warnings: list[str] = []
    floor_price = cost_total / (1 - config.margin_floor)

    chosen = [(a, s) for a, s in select_analogs(query, pool, config.top_k)
              if a.cost_value and a.cost_value > 0]
    model = win_model or local_win_model(query, pool, config)

    comparables = [
        {"deal_id": a.deal_id, "title": a.title, "contract_value": a.contract_value,
         "similarity": s, "retro_price_basis": a.retro_price_basis,
         "cost_value": a.cost_value, "price_index": round(a.contract_value / a.cost_value, 4),
         "outcome": a.outcome, "area_m2": a.area_m2}
        for a, s in chosen
    ]

    if len(chosen) >= config.min_indexed_analogs:
        mode = "hybrid"
        idx = [a.contract_value / a.cost_value for a, _ in chosen]
        wts = [s for _, s in chosen]
        q25, q50, q75 = (weighted_quantile(idx, wts, q) for q in (0.25, 0.5, 0.75))
        price_min = max(floor_price, cost_total * q25)
        price_max = max(cost_total * q75, price_min)
        if model:
            lo, hi = price_min / cost_total, price_max / cost_total
            grid = [lo + (hi - lo) * i / 200 for i in range(201)]
            probs = _probs(model, grid)
            best = max(zip(grid, probs, strict=True), key=lambda t: (t[0] - 1) * t[1])[0]
            price_opt = cost_total * best
            method = "max_expected_profit"
        else:
            won = [(i, w) for i, w, (a, _) in zip(idx, wts, chosen, strict=True)
                   if a.outcome == "won"]
            src = won if len(won) >= 2 else list(zip(idx, wts, strict=True))
            price_opt = cost_total * weighted_quantile([i for i, _ in src],
                                                       [w for _, w in src], 0.5)
            method = "weighted_median_won" if len(won) >= 2 else "weighted_median"
            price_opt = min(max(price_opt, price_min), price_max)
        index_stats = {"q25": round(q25, 4), "median": round(q50, 4), "q75": round(q75, 4),
                       "n": len(idx)}
        best_sim = max(wts)
        data_quality = "sufficient" if len(idx) >= 5 and best_sim >= 0.6 else "limited"
        if best_sim < 0.5:
            warnings.append("Слабое сходство аналогов: вилка ориентировочная")
        if all(a.retro_price_basis == "synthetic" for a, _ in chosen):
            warnings.append("Цены аналогов синтетические: расчёт демонстрационный")
    else:
        mode = "rule_based"
        price_min = floor_price
        price_opt = cost_total / (1 - config.margin_target)
        price_max = cost_total / (1 - config.margin_ceiling)
        method = "target_margin"
        index_stats = {"n": len(chosen)}
        data_quality = "limited"
        warnings.append("Похожих сделок мало: вилка построена от себестоимости и целевой "
                        "маржи, без рыночной проверки")

    if mode == "hybrid" and price_opt <= price_min * 1.001:
        warnings.append("Оптимум упирается в нижнюю границу вилки: похожие объекты продают "
                        "дешевле — проверьте состав и уровень проекта")
    win_p = model.p(price_opt / cost_total) if model else None
    if model and model.basis == "synthetic":
        warnings.append("Шанс выиграть — экспертная эвристика на демо-исходах, "
                        "не доказанная вероятность")

    lo_c, hi_c = min(cost_total * 1.05, price_min * 0.9), price_max * 1.15
    prices = [lo_c + (hi_c - lo_c) * i / (config.curve_points - 1)
              for i in range(config.curve_points)]
    curve_probs = _probs(model, [x / cost_total for x in prices]) if model else []
    curve = []
    for i, price in enumerate(prices):
        p = curve_probs[i] if model else None
        curve.append({
            "price": round(price, 2),
            "margin_pct": round(_margin(price, cost_total) * 100, 2),
            "win_prob": round(p * 100, 2) if p is not None else None,
            "expected_profit": round((price - cost_total) * p, 2) if p is not None else None,
        })

    return HybridResult(
        estimator_mode=mode,
        cost_total=round(cost_total, 2),
        price_min=round(price_min, 2),
        price_optimum=round(price_opt, 2),
        price_max=round(price_max, 2),
        margin_min=round(_margin(price_min, cost_total) * 100, 2),
        margin_optimum=round(_margin(price_opt, cost_total) * 100, 2),
        margin_max=round(_margin(price_max, cost_total) * 100, 2),
        win_probability=round(win_p * 100, 2) if win_p is not None else None,
        optimum_method=method,
        index_stats=index_stats,
        comparables=comparables,
        curve=curve,
        data_quality=data_quality,
        win_model=_describe_model(model, price_opt / cost_total),
        warnings=warnings,
    )


def _describe_model(model, index: float) -> dict | None:
    """Что за модель шанса стоит за ответом — показывается на экране и в КП (внутреннем)."""
    if model is None:
        return None
    if hasattr(model, "factors"):
        return {"type": "multifactor", **model.model.quality.as_dict(),
                "factors": model.factors(index)}
    return {"type": "single_factor",
            "model": "LogisticRegression (scikit-learn), наценка, ближайшие сделки",
            "a": round(model.a, 4), "b": round(model.b, 4), "n": model.n,
            "basis": model.basis}


def payment_options(price: float, config: PriceConfig | None = None) -> list[dict]:
    """Схемы финансирования: себестоимость та же, меняется график и сумма платежей."""
    config = config or PriceConfig()
    r = config.annual_rate / 12

    def annuity(n: int) -> float:
        return price * r / (1 - (1 + r) ** -n) if r > 0 else price / n

    inst = annuity(config.installment_months)
    opex = annuity(config.opex_months) + config.opex_service_fee
    return [
        {"scheme": "capex", "label": "Единовременно", "months": 1,
         "monthly": round(price, 2), "total": round(price, 2), "overpayment": 0.0},
        {"scheme": "installment", "label": f"Рассрочка {config.installment_months} мес.",
         "months": config.installment_months, "monthly": round(inst, 2),
         "total": round(inst * config.installment_months, 2),
         "overpayment": round(inst * config.installment_months - price, 2)},
        {"scheme": "opex", "label": f"Сервис {config.opex_months} мес.",
         "months": config.opex_months, "monthly": round(opex, 2),
         "total": round(opex * config.opex_months, 2),
         "overpayment": round(opex * config.opex_months - price, 2),
         "service_fee": config.opex_service_fee},
    ]
