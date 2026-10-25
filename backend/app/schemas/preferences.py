from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas import CompanyExportFilters, InvestmentExportFilters, ORMModel


class RadarFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region_id: int | None = Field(None, gt=0)
    industry_group: str | None = Field(None, max_length=64)
    municipality: str | None = Field(None, max_length=255)
    report_year: int | None = Field(None, ge=1900, le=2200)
    level: Literal["region", "municipality"] | None = None
    service_type: str | None = Field(None, max_length=64)


class TenderFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str | None = Field(None, max_length=128)
    region_id: int | None = Field(None, gt=0)
    industry_id: int | None = Field(None, gt=0)
    status: str | None = Field(None, max_length=24)


def validate_filters(module: str, filters: dict) -> dict:
    schema = {
        "companies": CompanyExportFilters,
        "radar": RadarFilters,
        "investments": InvestmentExportFilters,
        "tenders": TenderFilters,
    }.get(module)
    if schema is None:
        raise ValueError("Неизвестный модуль фильтров")
    return schema.model_validate(filters).model_dump(exclude_none=True)


class SavedFilterIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    module: Literal["companies", "radar", "investments"]
    name: str = Field(min_length=1, max_length=128)
    filters: dict = Field(default_factory=dict)
    is_default: bool = False

    @model_validator(mode="after")
    def checked(self):
        self.filters = validate_filters(self.module, self.filters)
        return self


class SavedFilterPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(None, min_length=1, max_length=128)
    filters: dict | None = None
    is_default: bool | None = None


class SavedFilterOut(ORMModel):
    id: int
    module: str
    name: str
    filters_json: dict
    is_default: bool


class SubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    module: Literal["investments", "tenders"]
    filters: dict = Field(default_factory=dict)
    notify_frequency: Literal["immediate", "hourly", "daily", "weekly"] = "daily"

    @model_validator(mode="after")
    def checked(self):
        self.filters = validate_filters(self.module, self.filters)
        return self


class SubscriptionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: dict | None = None
    notify_frequency: Literal["immediate", "hourly", "daily", "weekly"] | None = None
    is_active: bool | None = None
