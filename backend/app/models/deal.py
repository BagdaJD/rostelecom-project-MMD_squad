"""Сделки, справочник цен, исторические контракты (ТЗ 6.4)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class HistoricalDeal(Base):
    __tablename__ = "historical_deal"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    project_type: Mapped[str] = mapped_column(String(64), index=True)
    scale: Mapped[str | None] = mapped_column(String(64))
    scope_json: Mapped[dict | None] = mapped_column(JSON)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("region.id"), index=True)
    industry_id: Mapped[int | None] = mapped_column(ForeignKey("industry.id"), index=True)
    started_at: Mapped[date | None] = mapped_column(Date)
    closed_at: Mapped[date | None] = mapped_column(Date)
    contract_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))

    retro_price_basis: Mapped[str] = mapped_column(String(16), default="synthetic")
    financing_scheme: Mapped[str | None] = mapped_column(String(64))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source_record.id"))


class PositionPrice(Base):
    """Цены на оборудование, ПО и работы: без них параметры «оборудование и ПО» неоткуда считать."""

    __tablename__ = "position_price"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(32))
    unit: Mapped[str] = mapped_column(String(32))
    price_min: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    price_max: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    price_typical: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    region_id: Mapped[int | None] = mapped_column(ForeignKey("region.id"))
    price_period: Mapped[str | None] = mapped_column(String(16))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source_record.id"))
    is_synthetic: Mapped[bool] = mapped_column(default=True)


class RegionalCoefficient(Base):
    __tablename__ = "regional_coefficient"

    id: Mapped[int] = mapped_column(primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("region.id"), index=True)
    work_type: Mapped[str] = mapped_column(String(64))
    coefficient: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    effective_from: Mapped[date] = mapped_column(Date)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source_record.id"))


class Deal(Base):
    __tablename__ = "deal"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), index=True)
    input_params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="draft")


class DealEstimate(Base):
    __tablename__ = "deal_estimate"

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deal.id"), index=True)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    price_min: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    price_optimum: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    price_max: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    comparables_json: Mapped[list] = mapped_column(JSON, default=list)
    adjustments_json: Mapped[list] = mapped_column(JSON, default=list)
    price_period: Mapped[str | None] = mapped_column(String(32))

    data_quality: Mapped[str] = mapped_column(String(16), default="limited")

    estimator_mode: Mapped[str] = mapped_column(String(16), default="analogs")
    model_version: Mapped[str] = mapped_column(String(48))
    requires_human_approval: Mapped[bool] = mapped_column(default=True)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DealBreakdown(Base):
    __tablename__ = "deal_breakdown"

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_estimate_id: Mapped[int] = mapped_column(ForeignKey("deal_estimate.id"), index=True)
    article: Mapped[str] = mapped_column(String(48))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    basis: Mapped[str | None] = mapped_column(String(255))


class ProposalExport(Base):
    __tablename__ = "proposal_export"

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_estimate_id: Mapped[int] = mapped_column(ForeignKey("deal_estimate.id"), index=True)
    format: Mapped[str] = mapped_column(String(8), default="docx")
    file_ref: Mapped[str] = mapped_column(String(1024))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
