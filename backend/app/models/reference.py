"""Справочники, география, компании и показатели (ТЗ 6.1–6.2)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from geoalchemy2 import Geometry
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Region(Base):
    __tablename__ = "region"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("region.id"))
    geometry: Mapped[str | None] = mapped_column(Geometry("MULTIPOLYGON", srid=4326))

    center_lon: Mapped[float | None] = mapped_column(Numeric(9, 6))
    center_lat: Mapped[float | None] = mapped_column(Numeric(9, 6))


class Industry(Base):
    __tablename__ = "industry"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(255))

    group: Mapped[str] = mapped_column(String(64), index=True)


class OkvedToIndustry(Base):
    __tablename__ = "okved_to_industry"

    okved_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    industry_id: Mapped[int] = mapped_column(ForeignKey("industry.id"), primary_key=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("1.000"))


class DictionaryItem(Base):
    """Контролируемые словари: стадии, потребности, схемы финансирования, виды работ."""

    __tablename__ = "dictionary_item"
    __table_args__ = (UniqueConstraint("code", "dict_code", name="uq_dictionary_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dict_code: Mapped[str] = mapped_column(String(64), index=True)
    code: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(255))
    order_no: Mapped[int] = mapped_column(Integer, default=0)


class Company(Base):
    __tablename__ = "company"
    __table_args__ = (Index("ix_company_region_industry", "region_id", "industry_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(512), index=True)
    name_normalized: Mapped[str] = mapped_column(String(512), index=True)
    inn: Mapped[str | None] = mapped_column(String(12), index=True)
    ogrn: Mapped[str | None] = mapped_column(String(15), index=True)
    industry_id: Mapped[int | None] = mapped_column(ForeignKey("industry.id"))
    region_id: Mapped[int | None] = mapped_column(ForeignKey("region.id"), index=True)
    coordinates = mapped_column(Geometry("POINT", srid=4326))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    municipality: Mapped[str | None] = mapped_column(String(255), index=True)
    city: Mapped[str | None] = mapped_column(String(255))
    settlement: Mapped[str | None] = mapped_column(String(255))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source_record.id"))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    attributes_json: Mapped[dict | None] = mapped_column(JSON)

    client_status: Mapped[str] = mapped_column(String(16), default="unknown", index=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=datetime.now
    )

    metrics: Mapped[list[CompanyMetric]] = relationship(back_populates="company")


class CompanyMetric(Base):
    """Временной ряд показателей: динамика выручки невозможна без него (ТЗ 6.2)."""

    __tablename__ = "company_metric"
    __table_args__ = (
        UniqueConstraint("company_id", "metric_code", "period_year", "source_id"),
        Index("ix_company_metric_industry_year", "period_year", "metric_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"), index=True)
    metric_code: Mapped[str] = mapped_column(String(32))
    period_year: Mapped[int] = mapped_column(Integer)

    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    unit: Mapped[str] = mapped_column(String(16), default="RUB mln")
    source_id: Mapped[int] = mapped_column(ForeignKey("source_record.id"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    company: Mapped[Company] = relationship(back_populates="metrics")


class CompanyAlias(Base):
    __tablename__ = "company_alias"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"), index=True)
    alias_name: Mapped[str] = mapped_column(String(512))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source_record.id"))


class CompanyMatch(Base):
    """Причина объединения дублей видна в карточке (критерий «чистота, логика»)."""

    __tablename__ = "company_match"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"), index=True)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_record.id"), index=True)
    match_method: Mapped[str] = mapped_column(String(24))  # inn | ogrn | name_region
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))


class CustomerPresence(Base):
    __tablename__ = "customer_presence"
    __table_args__ = (Index("ix_presence_region_service_date", "region_id", "service_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("region.id"))
    municipality: Mapped[str | None] = mapped_column(String(255))
    service_type: Mapped[str] = mapped_column(String(64))
    coverage_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    contracts_count: Mapped[int | None] = mapped_column(Integer)
    as_of_date: Mapped[date] = mapped_column(Date)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source_record.id"))
    is_synthetic: Mapped[bool] = mapped_column(default=True)


class MarketEntrySignal(Base):
    """Вход федеральных и кросс-региональных игроков — требование кейса."""

    __tablename__ = "market_entry_signal"
    event_key: Mapped[str | None] = mapped_column(String(64), unique=True)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"), index=True)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("region.id"), index=True)
    signal_type: Mapped[str] = mapped_column(String(32))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source_record.id"))
