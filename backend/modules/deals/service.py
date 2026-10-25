"""Калькулятор сделок: параметры → диапазон по аналогам (модуль deals)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Deal,
    DealBreakdown,
    DealEstimate,
    HistoricalDeal,
    PositionPrice,
    RegionalCoefficient,
)
from app.schemas import Adjustment, ComparableOut, DealEstimateRequest, DealEstimateResponse
from ml.deal_estimator import Analog, EstimateInput, estimate_deal

MODEL_VERSION = "deal-estimator-0.1"
ARTICLE_WEIGHTS = {"works": 0.55, "equipment": 0.30, "software": 0.15}


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
        model_version=MODEL_VERSION,
    )
    session.add(estimate_row)
    session.flush()

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
        model_version=MODEL_VERSION,
        warning=result.warning,
    )


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
