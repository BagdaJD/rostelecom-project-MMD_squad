from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.schemas import CompanyOut, ProjectOut


class ProvenanceOut(BaseModel):
    id: int
    source: str
    external_id: str | None
    fetched_at: datetime
    license_note: str | None
    source_url: str | None = None
    source_file: str | None = None
    sheet: str | None = None
    row: int | None = None
    is_synthetic: bool = False


class MetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    metric_code: str
    period_year: int
    value: Decimal | None
    unit: str
    source_id: int
    fetched_at: datetime
    is_synthetic: bool = False


class CompanyCardOut(CompanyOut):
    ogrn: str | None
    employee_count: int | None
    metrics: list[MetricOut]
    presence: list[dict]
    presence_scope: str = "region"
    provenance: list[ProvenanceOut]
    demand_signals: list[str]
    projects: list[ProjectOut]
    attributes: dict
    warnings: list[str]


class RegionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    parent_id: int | None
    center_lon: Decimal | None
    center_lat: Decimal | None


class IndustryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    group: str


class DictionaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    label: str
    order_no: int


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    category: str
    unit: str
    price_min: Decimal | None
    price_max: Decimal | None
    price_typical: Decimal | None
    region_id: int | None
    price_period: str | None
    is_synthetic: bool


class ProjectCardOut(ProjectOut):
    description: str | None
    planned_end: date | None
    contact_window: str | None
    tenders: list[dict]
    milestones: list[dict]
    provenance: list[ProvenanceOut]
    stage_evidence: str | None
    warnings: list[str]
