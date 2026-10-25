"""Инвестиционные проекты, закупки и потребности (ТЗ 6.3)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from geoalchemy2 import Geometry
from sqlalchemy import (
    JSON,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class InvestmentProject(Base):
    __tablename__ = "investment_project"
    __table_args__ = (Index("ix_project_stage_start", "stage", "planned_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(512), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    initiator_company_id: Mapped[int | None] = mapped_column(ForeignKey("company.id"), index=True)
    industry_id: Mapped[int | None] = mapped_column(ForeignKey("industry.id"), index=True)
    # design | modernization | construction | launch | completed
    stage: Mapped[str] = mapped_column(String(32), index=True)
    planned_start: Mapped[date | None] = mapped_column(Date)
    planned_end: Mapped[date | None] = mapped_column(Date)
    estimated_budget: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    region_id: Mapped[int | None] = mapped_column(ForeignKey("region.id"), index=True)
    coordinates = mapped_column(Geometry("POINT", srid=4326))
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source_record.id"))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    status: Mapped[str] = mapped_column(String(24), default="active")

    needs: Mapped[list[ProjectNeed]] = relationship(back_populates="project")


class ProjectMilestone(Base):
    __tablename__ = "project_milestone"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("investment_project.id"), index=True)
    stage: Mapped[str] = mapped_column(String(32))
    planned_date: Mapped[date | None] = mapped_column(Date)
    actual_date: Mapped[date | None] = mapped_column(Date)
    evidence_url: Mapped[str | None] = mapped_column(String(1024))


class Tender(Base):
    __tablename__ = "tender"
    __table_args__ = (Index("ix_tender_deadline", "deadline_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_company_id: Mapped[int | None] = mapped_column(ForeignKey("company.id"), index=True)
    title: Mapped[str] = mapped_column(String(1024))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    publication_date: Mapped[date | None] = mapped_column(Date)
    deadline_date: Mapped[date | None] = mapped_column(Date)
    category: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source_record.id"))
    status: Mapped[str] = mapped_column(String(24), default="published")


class ProjectTender(Base):
    """N:M между проектом и закупкой: у проекта связанных тендеров много (ТЗ 6.3)."""

    __tablename__ = "project_tender"

    project_id: Mapped[int] = mapped_column(ForeignKey("investment_project.id"), primary_key=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tender.id"), primary_key=True)
    link_method: Mapped[str] = mapped_column(String(24))  # external_ref | inn_keyword | manual
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.000"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))


class ProjectNeed(Base):
    __tablename__ = "project_need"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("investment_project.id"), index=True)
    need_category: Mapped[str] = mapped_column(String(48), index=True)
    probability: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    evidence: Mapped[str | None] = mapped_column(Text)
    rule_id: Mapped[str | None] = mapped_column(String(48))
    model_version: Mapped[str] = mapped_column(String(48))
    # Дополнительные доказательства NLP; NULL для старых результатов.
    details_json: Mapped[dict | None] = mapped_column(JSON)

    project: Mapped[InvestmentProject] = relationship(back_populates="needs")


class InvestmentEvent(Base):
    """Агрегат таймлайна: событие знает проект, регион и точку на карте (ТЗ 6.3)."""

    __tablename__ = "investment_event"
    __table_args__ = (Index("ix_event_date_region", "event_date", "region_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_date: Mapped[date] = mapped_column(Date)
    event_type: Mapped[str] = mapped_column(String(32))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("investment_project.id"), index=True)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("region.id"))
    industry_id: Mapped[int | None] = mapped_column(ForeignKey("industry.id"))
    title: Mapped[str | None] = mapped_column(String(512))
