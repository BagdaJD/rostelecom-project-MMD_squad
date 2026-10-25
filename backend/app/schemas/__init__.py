"""Схемы запросов и ответов. Общие поля доверия — раздел 8 ТЗ."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TrustMeta(BaseModel):
    """Каждый ответ модели знает метод, версию, качество данных и дату расчёта."""

    scoring_mode: str = "heuristic"
    model_version: str = "0.1"
    confidence: str = "low"
    data_quality: str = "limited"
    calculated_at: datetime


class Factor(BaseModel):
    code: str
    label: str
    contribution: float
    value: str | None = None


class LoginRequest(BaseModel):
    login: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=256)


class LoginResponse(BaseModel):
    mfa_required: bool
    partial_token: str | None = None
    mfa_setup_required: bool = False


class Verify2FARequest(BaseModel):
    partial_token: str
    code: str = Field(min_length=6, max_length=10)


class Setup2FARequest(BaseModel):
    partial_token: str = Field(min_length=1, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    csrf_token: str
    backup_codes: list[str] | None = None


class CompanyOut(ORMModel):
    id: int
    name: str
    inn: str | None
    industry_id: int | None
    region_id: int | None
    client_status: str
    revenue_latest: Decimal | None = None
    revenue_year: int | None = None
    revenue_yoy: float | None = None
    revenue_is_synthetic: bool = False
    score: float | None = None
    municipality: str | None = None
    city: str | None = None
    settlement: str | None = None
    is_synthetic: bool = False
    source_id: int | None = None


class HeatCellOut(BaseModel):
    region_id: int
    region_name: str
    industry_group: str
    municipality: str | None = None
    geography_level: str = "region"
    companies_count: int
    revenue_sum: Decimal | None
    growth_share: float | None
    potential_score: float
    presence_score: float | None
    revenue_year: int | None = None
    revenue_companies: int = 0
    growth_companies: int = 0
    scoring_mode: str = "heuristic"
    model_version: str = "radar-scoring-0.2"
    confidence: str = "low"
    data_quality: str = "limited"
    calculated_at: datetime | None = None
    factors: list[Factor] = []
    is_synthetic: bool = False

    longitude: float | None = None
    latitude: float | None = None


class WhiteSpaceOut(BaseModel):
    region_id: int
    region_name: str
    industry_group: str
    municipality: str | None = None
    geography_level: str = "region"
    service_type: str | None = None
    potential_score: float
    presence_score: float
    explanation: list[str]
    scoring_mode: str = "heuristic"
    model_version: str = "radar-scoring-0.2"
    confidence: str = "low"
    data_quality: str = "limited"
    calculated_at: datetime | None = None
    is_synthetic: bool = False
    thresholds: dict[str, float] = {}


class ProjectOut(ORMModel):
    id: int
    title: str
    stage: str
    planned_start: date | None
    estimated_budget: Decimal | None
    region_id: int | None
    initiator_company_id: int | None
    source_url: str | None
    municipality: str | None = None
    industry_id: int | None = None
    planned_start_year: int | None = None
    planned_end_year: int | None = None
    start_precision: str = "day"
    end_precision: str = "day"
    stage_method: str = "source"
    is_synthetic: bool = False


class NeedOut(ORMModel):
    need_category: str
    probability: float | None
    evidence: str | None
    rule_id: str | None
    model_version: str


class TimelinePointOut(BaseModel):
    period: str
    region_id: int | None
    industry_id: int | None
    events_count: int
    project_ids: list[int]
    date_precision: str = "day"


class DealEstimateRequest(BaseModel):
    project_type: str
    scale: str
    region_id: int | None = None
    industry_id: int | None = None
    works: list[str] = []
    equipment: list[str] = []
    software: list[str] = []
    urgency: str = "normal"
    financing_scheme: str | None = None
    has_unique_solution: bool = False


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


class DealEstimateResponse(BaseModel):
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


class CompanyExportFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    region_id: int | None = Field(None, gt=0)
    industry_id: int | None = Field(None, gt=0)
    industry_group: str | None = Field(None, max_length=64)
    client_status: Literal["active", "prospect", "unknown"] | None = None
    min_revenue: float | None = Field(None, ge=0)
    min_growth: float | None = None
    municipality: str | None = Field(None, max_length=255)
    q: str | None = Field(None, min_length=1, max_length=255)
    report_year: int | None = Field(None, ge=1900, le=2200)


class InvestmentExportFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_id: int | None = Field(None, gt=0)
    industry_id: int | None = Field(None, gt=0)
    initiator_company_id: int | None = Field(None, gt=0)
    stage: (
        Literal["design", "modernization", "construction", "launch", "completed", "unknown"] | None
    ) = None
    municipality: str | None = Field(None, max_length=255)
    q: str | None = Field(None, min_length=1, max_length=255)


class ExportCsvRequest(BaseModel):
    module: Literal["companies", "investments"]
    filters: dict = {}
    mode: Literal["general", "crm"] = "general"

    @model_validator(mode="after")
    def validate_filters(self):
        schema = CompanyExportFilters if self.module == "companies" else InvestmentExportFilters
        self.filters = schema.model_validate(self.filters).model_dump(exclude_none=True)
        return self


class SubscriptionIn(BaseModel):
    module: str
    filters: dict = {}
    notify_frequency: str = "daily"


class NotificationOut(ORMModel):
    id: int
    type: str
    payload_json: dict
    related_object: str | None
    created_at: datetime
    read_at: datetime | None
