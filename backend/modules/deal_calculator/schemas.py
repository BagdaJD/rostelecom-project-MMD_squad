"""Схемы API калькулятора (/calculator/*). Общие схемы app/schemas не используются и не меняются."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class ItemIn(BaseModel):
    code: str
    qty: float = Field(ge=0, le=100_000)


class CustomItemIn(BaseModel):
    """Позиция вне каталога: нестандартное оборудование или ПО."""

    name: str = Field(min_length=1, max_length=255)
    qty: float = Field(gt=0, le=100_000)
    unit_price: float = Field(ge=0, le=1_000_000_000)
    kind: Literal["equipment", "software"] = "equipment"
    nonstandard: bool = True


class EstimateRequest(BaseModel):
    project_type: Literal["dispatching"] = "dispatching"
    object_type: str | None = None
    area_m2: float | None = Field(default=None, gt=0, le=1_000_000)
    #: id из calc_region (список — в GET /calculator/catalog).
    region_id: int | None = None
    systems: list[str] | None = None  # группы систем для автоподбора, если items пуст
    project_level: Literal["basic", "advanced", "expert"] = "basic"
    items: list[ItemIn] = []
    custom_items: list[CustomItemIn] = []
    duration_months: float | None = Field(default=None, gt=0, le=120)
    has_unique_solution: bool = False
    #: budget — госзаказчик (44-ФЗ): учитывается моделью шанса выиграть.
    financing_scheme: str | None = None
    payment_scheme: Literal["capex", "installment", "opex"] = "capex"
    investment_project_id: int | None = None
    company_id: int | None = None


class Adjustment(BaseModel):
    factor: str
    value: float
    note: str | None = None


class ComparableOut(BaseModel):
    deal_id: int
    title: str
    contract_value: Decimal
    similarity: float
    retro_price_basis: str
    cost_value: float | None = None
    price_index: float | None = None
    outcome: str | None = None
    area_m2: float | None = None


class EstimateResponse(BaseModel):
    estimate_id: int
    currency: str = "RUB"
    estimate: dict[str, Decimal]
    estimator_mode: str
    confidence: str
    data_quality: str
    comparables: list[ComparableOut]
    adjustments: list[Adjustment]
    breakdown: list[dict]
    price_period: str | None
    model_version: str
    requires_human_approval: bool = True
    warning: str | None = None
    cost: dict | None = None  # total, breakdown, factors, lines, points, norm_months
    margin: dict[str, float] | None = None  # min / optimum / max, % от цены
    win_probability: float | None = None
    optimum_method: str | None = None
    index_stats: dict | None = None
    curve: list[dict] = []
    payment_options: list[dict] = []
    payment_scheme: str | None = None
    warnings: list[str] = []
    approved_price: Decimal | None = None
    #: Модель шанса выиграть: тип, качество на отложенной выборке, вклад факторов (п.п.).
    win_model: dict | None = None


class ApproveIn(BaseModel):
    price: float = Field(gt=0, le=10_000_000_000)
