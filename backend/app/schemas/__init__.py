"""Схемы запросов и ответов. Общие поля доверия — раздел 8 ТЗ."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


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


# --- auth ---
class LoginRequest(BaseModel):
    login: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=256)


class LoginResponse(BaseModel):
    mfa_required: bool
    partial_token: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None


class Verify2FARequest(BaseModel):
    partial_token: str
    code: str = Field(min_length=6, max_length=10)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# --- companies / radar ---
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
    score: float | None = None


class HeatCellOut(BaseModel):
    region_id: int
    region_name: str
    industry_group: str
    companies_count: int
    revenue_sum: Decimal | None
    growth_share: float | None
    potential_score: float
    presence_score: float | None
    # Центр агрегата: карта рисует кружки по нему, если полигона нет (ТЗ 11.3).
    longitude: float | None = None
    latitude: float | None = None
    data_quality: str | None = None
    presence_status: str | None = None
    model_version: str | None = None
    aggregation_level: str | None = None


class WhiteSpaceOut(BaseModel):
    region_id: int
    region_name: str
    industry_group: str
    service_type: str | None = None
    potential_score: float
    presence_score: float
    explanation: list[str]


# --- investments ---
class ProjectOut(ORMModel):
    id: int
    title: str
    stage: str
    planned_start: date | None
    estimated_budget: Decimal | None
    region_id: int | None
    initiator_company_id: int | None
    source_url: str | None


class NeedOut(ORMModel):
    need_category: str
    probability: float | None
    evidence: str | None
    rule_id: str | None
    model_version: str
    evidence_type: str | None = None
    reason: str | None = None
    semantic_similarity: float | None = None
    confidence_label: str | None = None
    data_quality: str | None = None


class TimelinePointOut(BaseModel):
    period: str
    region_id: int | None
    industry_id: int | None
    events_count: int
    project_ids: list[int]


# --- deals ---
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
    #: id сохранённой оценки — нужен, чтобы по ней собрать DOCX (exports/proposal).
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


# --- exports / subscriptions ---
class ExportCsvRequest(BaseModel):
    module: str
    filters: dict = {}
    mode: str = "general"


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
