"""Калькулятор сделок (модуль 3): параметры → себестоимость → вилка → утверждение → КП.

Себестоимость считается по справочникам кейса (``ml/deal_cost``), вилка = себестоимость ×
наценка похожих сделок, оптимум — максимум ожидаемой прибыли (``ml/deal_pricing``), шанс
выиграть — многофакторная модель (``ml/win_model``).

Работает на своих таблицах ``calc_*`` (``modules/deal_calculator/models.py``). Из общих
таблиц только читается инвестпроект для черновика («Оценить сделку» из навигатора).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ml.deal_cost import (
    ARTICLE_LABELS,
    OBJECT_TYPES,
    SYSTEM_TEMPLATES,
    CatalogItem,
    CostInput,
    CustomLine,
    LineInput,
    PricingConfig,
    calculate_cost,
    estimate_area_m2,
    guess_object_type,
    parse_area_m2,
    suggest_items,
)
from ml.deal_pricing import Analog, EstimateInput, PriceConfig, estimate_hybrid, payment_options
from ml.win_model import DealRow, TrainedWinModel
from ml.win_model import train as train_win_model
from modules.deal_calculator.models import (
    CalcDeal,
    CalcDictionary,
    CalcEstimate,
    CalcPosition,
    CalcRegion,
)
from modules.deal_calculator.schemas import (
    Adjustment,
    ComparableOut,
    EstimateRequest,
    EstimateResponse,
)

MODEL_VERSION = "deal-calculator-1.0"
DISPATCHING = "dispatching"
ZONE_PREFIX = "ZONE-"
ARTICLE_BASIS = {
    "equipment": "количество × цена каталога (МОД3_Таб4)",
    "installation": "оборудование × (сложность − 1) — трактовка «монтаж»",
    "design": "10% от оборудования × сложность × уровень (МОД3_Таб3)",
    "commissioning": "15% от оборудования × сложность × уровень (МОД3_Таб3)",
    "supervision": "5% от оборудования × сложность × уровень (МОД3_Таб3)",
    "software": "позиции ПО по цене менеджера",
    "reserve": "резерв на нестандартные позиции",
    "margin": "цена − себестоимость",
}


# ------------------------------- справочники ----------------------------------------------
def load_catalog(session: Session) -> dict[str, CatalogItem]:
    return {
        p.code: CatalogItem(p.code, p.name, p.system_group, float(p.price),
                            float(p.complexity_coef or 1), p.unit)
        for p in session.scalars(select(CalcPosition)).all() if p.price
    }


def _dictionary(session: Session, dict_code: str) -> list[CalcDictionary]:
    return list(session.scalars(select(CalcDictionary)
                                .where(CalcDictionary.dict_code == dict_code)
                                .order_by(CalcDictionary.order_no)))


def complexity_mode() -> str:
    """Трактовка коэффициента сложности МОД3_Таб4 — кейс её не уточняет (works по умолчанию)."""
    mode = os.getenv("DEAL_COMPLEXITY_MODE", "works")
    return mode if mode in ("works", "installation", "equipment") else "works"


def pricing_config(session: Session) -> PricingConfig:
    """Доли работ и уровни — из справочников кейса; если их нет — значения по умолчанию."""
    defaults = PricingConfig()
    shares = {i.code: float(i.value) for i in _dictionary(session, "work_stage")
              if i.value is not None}
    levels = {i.code: float(i.value) for i in _dictionary(session, "project_level")
              if i.value is not None}
    return PricingConfig(
        work_shares=shares or defaults.work_shares,
        level_coefficients=levels or defaults.level_coefficients,
        complexity_mode=complexity_mode(),  # type: ignore[arg-type]
    )


class Regions:
    """Регионы калькулятора одним запросом: коэффициент ищется вверх по иерархии до зоны."""

    def __init__(self, session: Session) -> None:
        rows = session.scalars(select(CalcRegion)).all()
        self.by_id = {r.id: r for r in rows}
        self.by_code = {r.code: r for r in rows}

    def get(self, region_id: int | None) -> CalcRegion | None:
        return self.by_id.get(region_id) if region_id else None

    def coefficient(self, region_id: int | None) -> tuple[float, str | None]:
        current = self.get(region_id)
        label = current.name if current else None
        seen: set[str] = set()
        while current is not None and current.code not in seen:
            seen.add(current.code)
            if current.coefficient is not None:
                return float(current.coefficient), label
            current = self.by_code.get(current.parent_code or "")
        return 1.0, label

    def subject_code(self, code: str | None) -> str | None:
        """Для сходства и модели район = его субъект.

        «Азовский район» и «Ростовская область» — одно.
        """
        current = self.by_code.get(code or "")
        if current is None:
            return code
        while current.parent_code:
            parent = self.by_code.get(current.parent_code)
            if parent is None or parent.code.startswith(ZONE_PREFIX):
                break
            current = parent
        return current.code

    def subject_id(self, code: str | None) -> int | None:
        top = self.by_code.get(self.subject_code(code) or "")
        return top.id if top else None


_WIN_MODEL_CACHE: dict[tuple, TrainedWinModel | None] = {}


def win_model(deals: list[CalcDeal], regions: Regions) -> TrainedWinModel | None:
    """Многофакторная модель шанса выиграть; переобучается, когда меняется история сделок."""
    key = (len(deals), max((d.id for d in deals), default=0),
           sum(1 for d in deals if d.outcome))
    if key not in _WIN_MODEL_CACHE:
        rows = [
            DealRow(
                price_index=float(d.contract_value) / float(d.cost_value),
                area_m2=float(d.area_m2) if d.area_m2 else None,
                project_level=d.project_level,
                object_type=d.object_type,
                zone=regions.subject_code(d.region_code),
                payment_scheme=d.payment_scheme,
                budget_customer=d.financing_scheme == "budget",
                outcome=d.outcome,
                closed_at=d.closed_at,
                basis=d.retro_price_basis,
            )
            for d in deals if d.cost_value and d.outcome
        ]
        _WIN_MODEL_CACHE.clear()
        _WIN_MODEL_CACHE[key] = train_win_model(rows)
    return _WIN_MODEL_CACHE[key]


def _deals(session: Session, limit: int = 5000) -> list[CalcDeal]:
    return list(session.scalars(select(CalcDeal).limit(limit)).all())


def _pool(deals: list[CalcDeal], regions: Regions) -> list[Analog]:
    return [
        Analog(
            deal_id=d.id,
            title=d.title,
            contract_value=float(d.contract_value),
            project_type=d.project_type,
            scale=d.scale,
            region_id=regions.subject_id(d.region_code),
            retro_price_basis=d.retro_price_basis,
            features=tuple((d.scope_json or {}).get("features", [])),
            cost_value=float(d.cost_value) if d.cost_value else None,
            outcome=d.outcome,
            area_m2=float(d.area_m2) if d.area_m2 else None,
            object_type=d.object_type,
        )
        for d in deals
    ]


# ------------------------------- расчёт ---------------------------------------------------
def estimate(session: Session, payload: EstimateRequest, author_id: int | None) -> EstimateResponse:
    catalog = load_catalog(session)
    config = pricing_config(session)
    regions = Regions(session)
    k_region, region_label = regions.coefficient(payload.region_id)
    region = regions.get(payload.region_id)
    object_type = payload.object_type or "office"

    items = [LineInput(i.code, i.qty) for i in payload.items if i.qty > 0]
    if not items and payload.area_m2:
        items = suggest_items(object_type, payload.area_m2, payload.systems)
    custom = [CustomLine(c.name, c.qty, c.unit_price, c.kind, c.nonstandard)
              for c in payload.custom_items]
    cost = calculate_cost(
        CostInput(items=items, project_level=payload.project_level,
                  regional_coefficient=k_region, region_label=region_label,
                  duration_months=payload.duration_months,
                  has_unique_solution=payload.has_unique_solution, custom_lines=custom),
        catalog, config,
    )
    if cost.total <= 0:
        return _empty_response(session, payload, author_id, cost.warnings)

    systems = sorted({line["group"] for line in cost.lines if line.get("code")})
    region_code = region.code if region else None
    query = EstimateInput(
        project_type=DISPATCHING, region_id=regions.subject_id(region_code),
        works=systems, area_m2=payload.area_m2, object_type=object_type,
    )
    price_config = PriceConfig()
    deals = _deals(session)
    trained = win_model(deals, regions)
    bound = trained.bind(DealRow(
        price_index=1.0,
        area_m2=payload.area_m2,
        project_level=payload.project_level,
        object_type=object_type,
        zone=regions.subject_code(region_code),
        payment_scheme=payload.payment_scheme,
        budget_customer=payload.financing_scheme == "budget",
    )) if trained else None
    result = estimate_hybrid(query, _pool(deals, regions), cost.total, price_config,
                             win_model=bound)
    payments = payment_options(result.price_optimum, price_config)

    breakdown = [
        {"article": k, "label": ARTICLE_LABELS.get(k, k), "amount": v,
         "basis": ARTICLE_BASIS.get(k)}
        for k, v in cost.breakdown.items()
    ]
    sale_breakdown = [*breakdown, {"article": "margin", "label": "Маржа",
                                   "amount": round(result.price_optimum - cost.total, 2),
                                   "basis": ARTICLE_BASIS["margin"]}]
    cost_payload = {
        "total": cost.total,
        "breakdown": breakdown,
        "factors": [f.__dict__ for f in cost.factors],
        "lines": cost.lines,
        "points": cost.points,
        "norm_months": cost.norm_months,
        "object_type": object_type,
        "object_label": OBJECT_TYPES.get(object_type, {}).get("label"),
        "area_m2": payload.area_m2,
        "complexity_mode": config.complexity_mode,
        "region_label": region_label,
        "systems": systems,
        "win_model": result.win_model,
    }
    warnings = cost.warnings + result.warnings

    row = CalcEstimate(
        author_id=author_id,
        investment_project_id=payload.investment_project_id,
        company_id=payload.company_id or _project_company(session, payload.investment_project_id),
        request_json=payload.model_dump(mode="json"),
        price_min=_dec(result.price_min),
        price_optimum=_dec(result.price_optimum),
        price_max=_dec(result.price_max),
        cost_total=_dec(cost.total),
        margin_min=_dec(result.margin_min),
        margin_optimum=_dec(result.margin_optimum),
        margin_max=_dec(result.margin_max),
        win_probability=_dec(result.win_probability),
        estimator_mode=result.estimator_mode,
        optimum_method=result.optimum_method,
        data_quality=result.data_quality,
        model_version=MODEL_VERSION,
        comparables_json=result.comparables,
        adjustments_json=[f.__dict__ for f in cost.factors],
        cost_json=cost_payload,
        curve_json=result.curve,
        payment_json=payments,
    )
    session.add(row)
    session.commit()

    return EstimateResponse(
        estimate_id=row.id,
        estimate={"min": _dec(result.price_min), "optimum": _dec(result.price_optimum),
                  "max": _dec(result.price_max)},
        estimator_mode=result.estimator_mode,
        confidence="medium" if result.data_quality == "sufficient" else "low",
        data_quality=result.data_quality,
        comparables=[ComparableOut(**c) for c in result.comparables],
        adjustments=[Adjustment(factor=f.factor, value=f.value, note=f"{f.note} ({f.source})")
                     for f in cost.factors],
        breakdown=[{"article": b["article"], "label": b["label"], "amount": _dec(b["amount"])}
                   for b in sale_breakdown],
        price_period=_period_label(session),
        model_version=MODEL_VERSION,
        warning=warnings[0] if warnings else None,
        cost=cost_payload,
        margin={"min": result.margin_min, "optimum": result.margin_optimum,
                "max": result.margin_max},
        win_probability=result.win_probability,
        optimum_method=result.optimum_method,
        index_stats=result.index_stats,
        curve=result.curve,
        payment_options=payments,
        payment_scheme=payload.payment_scheme,
        warnings=warnings,
        win_model=result.win_model,
    )


def approve(session: Session, estimate_id: int, price: float, user_id: int | None) -> CalcEstimate:
    """Сотрудник утверждает цену (ТЗ 8.3): она уходит в КП вместо оптимума."""
    row = session.get(CalcEstimate, estimate_id)
    if row is None:
        raise LookupError("Расчёт не найден")
    if row.cost_total and Decimal(str(price)) < row.cost_total:
        raise ValueError("Цена ниже себестоимости: такую сделку утвердить нельзя")
    row.approved_price = _dec(price)
    row.approved_by = user_id
    row.approved_at = datetime.now(UTC)
    session.commit()
    return row


# ------------------------------- справочник для формы -------------------------------------
def catalog_payload(session: Session) -> dict:
    """Всё, что нужно форме калькулятора: позиции, уровни, регионы, нормативы, параметры."""
    groups: dict[str, list[dict]] = {}
    for p in session.scalars(select(CalcPosition).order_by(CalcPosition.code)).all():
        groups.setdefault(p.system_group or "Прочее", []).append({
            "code": p.code, "name": p.name, "unit": p.unit,
            "price": float(p.price or 0),
            "complexity": float(p.complexity_coef or 1),
            "is_synthetic": p.is_synthetic,
        })
    system_order = list(SYSTEM_TEMPLATES)
    regions = Regions(session)
    parents = {r.code: r.id for r in regions.by_id.values()}
    region_list = []
    for r in sorted(regions.by_id.values(), key=lambda r: r.name):
        k, _ = regions.coefficient(r.id)
        region_list.append({"id": r.id, "code": r.code, "name": r.name,
                            "parent_id": parents.get(r.parent_code or ""),
                            "coefficient": k, "is_zone": r.code.startswith(ZONE_PREFIX)})
    config = pricing_config(session)
    price = PriceConfig()
    return {
        "systems": [{"group": g, "items": groups[g]}
                    for g in sorted(groups, key=lambda g: system_order.index(g)
                                    if g in system_order else 99)],
        "object_types": [{"code": k, "label": v["label"], "systems": v["systems"]}
                         for k, v in OBJECT_TYPES.items()],
        "project_levels": [{"code": i.code, "label": i.label, "value": float(i.value or 0),
                            "description": i.description}
                           for i in _dictionary(session, "project_level")],
        "work_stages": [{"code": i.code, "label": i.label, "value": float(i.value or 0),
                         "description": i.description}
                        for i in _dictionary(session, "work_stage")],
        "payment_schemes": [{"code": i.code, "label": i.label}
                            for i in _dictionary(session, "payment_scheme")],
        "regions": region_list,
        "settings": {
            "complexity_mode": config.complexity_mode,
            "margin_floor": price.margin_floor,
            "annual_rate": price.annual_rate,
            "installment_months": price.installment_months,
            "opex_months": price.opex_months,
            "opex_service_fee": price.opex_service_fee,
            "unique_solution_coefficient": config.unique_solution_coefficient,
            "nonstandard_reserve_share": config.nonstandard_reserve_share,
        },
    }


# ------------------------------- черновик из инвестпроекта --------------------------------
def draft_from_project(session: Session, project_id: int) -> dict | None:
    """Черновик параметров из инвестпроекта навигатора (модуль 2 → модуль 3). Только чтение."""
    from app.models import Company, InvestmentProject, Region

    project = session.get(InvestmentProject, project_id)
    if project is None:
        return None
    object_type = guess_object_type(project.title)
    area = parse_area_m2(project.title) or parse_area_m2(project.description)
    area_estimated = area is None
    if area is None:
        area = estimate_area_m2(object_type, float(project.estimated_budget or 0))
    duration = None
    if project.planned_start and project.planned_end:
        # Диспетчеризацию ставят под ввод: даём на неё до 6 месяцев из срока стройки.
        months = (project.planned_end - project.planned_start).days / 30.4
        duration = round(min(max(months, 1), 6), 1)
    company = None
    if project.initiator_company_id:
        c = session.get(Company, project.initiator_company_id)
        company = {"id": c.id, "name": c.name, "inn": c.inn} if c else None
    # Регион проекта → регион калькулятора по коду (у справочников разные id).
    region_id = None
    if project.region_id:
        source = session.get(Region, project.region_id)
        regions = Regions(session)
        match = regions.by_code.get(source.code) if source else None
        region_id = match.id if match else None
    items = suggest_items(object_type, area) if area else []
    return {
        "request": {
            "project_type": DISPATCHING,
            "object_type": object_type,
            "area_m2": area,
            "region_id": region_id,
            "project_level": "advanced" if object_type in ("retail", "office", "social")
            else "basic",
            "duration_months": duration,
            "payment_scheme": "capex",
            "items": [{"code": i.code, "qty": i.qty} for i in items],
            "investment_project_id": project.id,
            "company_id": project.initiator_company_id,
        },
        "explain": {
            "project_title": project.title,
            "object_type_label": OBJECT_TYPES[object_type]["label"],
            "object_type_from": "по названию проекта",
            "area_is_estimated": area_estimated,
            "area_from": "оценена по бюджету проекта — уточните" if area_estimated
            else "из описания проекта",
            "duration_from": "срок проекта, не более 6 мес. на диспетчеризацию",
            "company": company,
        },
    }


def _project_company(session: Session, project_id: int | None) -> int | None:
    if not project_id:
        return None
    from app.models import InvestmentProject

    try:
        project = session.get(InvestmentProject, project_id)
    except Exception:  # noqa: BLE001 — таблицы навигатора может не быть: черновик необязателен
        session.rollback()
        return None
    return project.initiator_company_id if project else None


def _empty_response(session: Session, payload: EstimateRequest, author_id: int | None,
                    warnings: list[str]) -> EstimateResponse:
    row = CalcEstimate(author_id=author_id, request_json=payload.model_dump(mode="json"),
                       price_min=Decimal(0), price_optimum=Decimal(0), price_max=Decimal(0),
                       estimator_mode="rule_based", data_quality="insufficient",
                       model_version=MODEL_VERSION)
    session.add(row)
    session.commit()
    msg = warnings or ["Укажите состав оборудования или площадь объекта"]
    return EstimateResponse(
        estimate_id=row.id, estimate={"min": Decimal(0), "optimum": Decimal(0), "max": Decimal(0)},
        estimator_mode="rule_based", confidence="low", data_quality="insufficient",
        comparables=[], adjustments=[], breakdown=[], price_period=None,
        model_version=MODEL_VERSION, warning=msg[0], warnings=msg,
    )


def _period_label(session: Session) -> str | None:
    """Период цен: пользователь обязан видеть, какими ценами считается вилка."""
    found = session.scalars(select(CalcPosition.price_period).distinct())
    periods = sorted({p for p in found if p})
    if not periods:
        return None
    return f"{periods[0]}–{periods[-1]}" if len(periods) > 1 else periods[0]


def _dec(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(round(float(value), 2)))
