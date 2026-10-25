"""Калькулятор сделок: параметры → диапазон по аналогам (модуль deals)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    Deal,
    DealBreakdown,
    DealEstimate,
    HistoricalDeal,
    PositionPrice,
    Region,
    RegionalCoefficient,
)
from app.schemas import Adjustment, ComparableOut, DealEstimateRequest, DealEstimateResponse
from ml.deal_estimator import (
    URGENCY_COEFFICIENT,
    Analog,
    EstimateInput,
    EstimateResult,
    estimate_deal,
)
from modules.deal_calculator import service as calculator
from modules.deal_calculator.models import CalcRegion
from modules.deal_calculator.schemas import EstimateRequest as CalculatorRequest

MODEL_VERSION = "deal-estimator-0.1"
ARTICLE_WEIGHTS = {"works": 0.55, "equipment": 0.30, "software": 0.15}

# Запасной расчёт, когда аналогов нет: старая форма не знает площади объекта, а новому
# калькулятору без неё нечего считать. Допущения согласованы с командой (задача 1).
FALLBACK_AREA_M2 = {"small": 1_000.0, "medium": 5_000.0, "large": 20_000.0}
FALLBACK_MODE = "fallback_dispatching_norms"


def _regional_coefficient(session: Session, region_id: int | None) -> float:
    if not region_id:
        return 1.0
    value = session.scalar(
        select(RegionalCoefficient.coefficient)
        .where(RegionalCoefficient.region_id == region_id)
        .order_by(RegionalCoefficient.effective_from.desc())
        .limit(1)
    )
    return float(value) if value is not None else 1.0


def _pool(session: Session, limit: int = 200) -> list[Analog]:
    deals = session.scalars(select(HistoricalDeal).limit(limit)).all()
    return [
        Analog(
            deal_id=d.id,
            title=d.title,
            contract_value=float(d.contract_value),
            project_type=d.project_type,
            scale=d.scale,
            region_id=d.region_id,
            retro_price_basis=d.retro_price_basis,
            features=tuple((d.scope_json or {}).get("features", [])),
        )
        for d in deals
    ]


def estimate(
    session: Session, payload: DealEstimateRequest, author_id: int | None
) -> DealEstimateResponse:
    query = EstimateInput(
        project_type=payload.project_type,
        scale=payload.scale,
        region_id=payload.region_id,
        works=list(payload.works),
        equipment=list(payload.equipment),
        software=list(payload.software),
        urgency=payload.urgency,
        financing_scheme=payload.financing_scheme,
        has_unique_solution=payload.has_unique_solution,
        regional_coefficient=_regional_coefficient(session, payload.region_id),
    )
    result = estimate_deal(query, _pool(session))
    model_version = MODEL_VERSION
    fallback_breakdown: dict[str, float] | None = None
    if not result.comparables:
        fallback = _dispatching_fallback(session, payload, author_id)
        if fallback is not None:
            result, fallback_breakdown, model_version = fallback

    wanted = set(payload.works) | set(payload.equipment) | set(payload.software)
    price_period = _period_label(session)

    deal = Deal(author_id=author_id, input_params_json=payload.model_dump())
    session.add(deal)
    session.flush()

    estimate_row = DealEstimate(
        deal_id=deal.id,
        price_min=Decimal(str(result.price_min)),
        price_optimum=Decimal(str(result.price_optimum)),
        price_max=Decimal(str(result.price_max)),
        comparables_json=result.comparables,
        adjustments_json=result.adjustments,
        data_quality=result.data_quality,
        estimator_mode=result.estimator_mode,
        price_period=price_period,
        model_version=model_version,
    )
    session.add(estimate_row)
    session.flush()

    if fallback_breakdown is not None:
        breakdown = fallback_breakdown
    else:
        breakdown = _breakdown(result.price_optimum, wanted)
    for article, amount in breakdown.items():
        session.add(
            DealBreakdown(
                deal_estimate_id=estimate_row.id,
                article=article,
                amount=Decimal(str(amount)),
                basis="доля статьи в стоимости по составу работ" if amount else None,
            )
        )

    return DealEstimateResponse(
        estimate_id=estimate_row.id,
        estimate={
            "min": Decimal(str(result.price_min)),
            "optimum": Decimal(str(result.price_optimum)),
            "max": Decimal(str(result.price_max)),
        },
        estimator_mode=result.estimator_mode,
        confidence="medium" if result.data_quality == "sufficient" else "low",
        data_quality=result.data_quality,
        comparables=[ComparableOut(**c) for c in result.comparables],
        adjustments=[Adjustment(**a) for a in result.adjustments],
        breakdown=[{"article": k, "amount": Decimal(str(v))} for k, v in breakdown.items()],
        price_period=price_period,
        model_version=model_version,
        warning=result.warning,
    )


def _dispatching_fallback(
    session: Session, payload: DealEstimateRequest, author_id: int | None
) -> tuple[EstimateResult, dict[str, float], str] | None:
    """Аналогов нет — оценка новым калькулятором по нормативам диспетчеризации здания.

    Вместо вилки 0 / 0 / 0 пользователь видит ориентир и явное предупреждение о допущениях.
    None — посчитать не удалось (нет данных калькулятора): остаётся прежний пустой ответ.
    """
    area = FALLBACK_AREA_M2[payload.scale]
    region_code = (
        session.scalar(select(Region.code).where(Region.id == payload.region_id))
        if payload.region_id
        else None
    )
    try:
        # Регионы калькулятора — своя таблица; совпадение только по коду субъекта.
        calc_region_id = (
            session.scalar(select(CalcRegion.id).where(CalcRegion.code == region_code))
            if region_code
            else None
        )
        response = calculator.estimate(
            session,
            CalculatorRequest(
                area_m2=area,
                region_id=calc_region_id,
                has_unique_solution=payload.has_unique_solution,
                financing_scheme=payload.financing_scheme,
            ),
            author_id,
        )
    except SQLAlchemyError:
        session.rollback()  # таблицы калькулятора не созданы
        return None
    if not response.estimate.get("optimum"):
        return None

    # У нового калькулятора нет срочности: применяем тот же коэффициент, что и по аналогам.
    k_urgency = URGENCY_COEFFICIENT[payload.urgency]
    prices = [float(response.estimate[key]) * k_urgency for key in ("min", "optimum", "max")]
    area_label = f"{area:,.0f}".replace(",", " ")
    region_note = (
        ""
        if calc_region_id
        else "; региональный коэффициент 1,0 — регион вне справочника калькулятора"
    )
    warning = (
        f"Аналогов нет: оценка по нормативам диспетчеризации инженерных систем здания, "
        f"площадь принята {area_label} м² по масштабу «{payload.scale}»{region_note}. "
        f"Для типа проекта «{payload.project_type}» требуется ручная проверка"
    )
    adjustments = [
        {
            "factor": "assumed_area_m2",
            "value": area,
            "note": f"площадь по масштабу «{payload.scale}» — допущение запасного расчёта",
        },
        *({"factor": a.factor, "value": a.value, "note": a.note} for a in response.adjustments),
    ]
    if k_urgency != 1.0:
        adjustments.append({"factor": "urgency", "value": k_urgency})
    result = EstimateResult(
        price_min=round(prices[0], 2),
        price_optimum=round(prices[1], 2),
        price_max=round(prices[2], 2),
        comparables=[
            {
                "deal_id": c.deal_id,
                "title": c.title,
                "contract_value": float(c.contract_value),
                "similarity": c.similarity,
                "retro_price_basis": c.retro_price_basis,
            }
            for c in response.comparables
        ],
        adjustments=adjustments,
        data_quality=response.data_quality,
        estimator_mode=FALLBACK_MODE,
        warning=warning,
    )
    breakdown = {
        row["article"]: round(float(row["amount"]) * k_urgency, 2) for row in response.breakdown
    }
    return result, breakdown, response.model_version


def _breakdown(optimum: float, features: set[str]) -> dict[str, float]:
    """Разбивка по статьям: без неё КП выглядит «магической» цифрой."""
    if optimum <= 0:
        return {}
    shares = {"works": ARTICLE_WEIGHTS["works"]}
    if features:
        has_equipment = any(f.startswith(("oborudovanie", "equipment")) for f in features)
        has_software = any(f.startswith(("po", "software")) for f in features)
        if has_equipment or has_software:
            shares = {
                "works": 0.5,
                "equipment": 0.28 if has_equipment else 0.0,
                "software": 0.22 if has_software else 0.0,
            }
            rest = 1 - sum(shares.values())
            shares["works"] += rest
    return {article: round(optimum * share, 2) for article, share in shares.items() if share > 0}


def _period_label(session: Session) -> str | None:
    """Период ретро-данных: пользователь обязан видеть, какими ценами считается вилка."""
    periods = session.scalars(select(PositionPrice.price_period).distinct()).all()
    periods = sorted({p for p in periods if p})
    if not periods:
        return None
    return f"{periods[0]}–{periods[-1]}" if len(periods) > 1 else periods[0]
