"""Таблицы калькулятора сделок (модуль 3).

Свои таблицы с префиксом ``calc_``: калькулятор не меняет общие модели и не зависит от того,
заполнены ли справочники других модулей. Внешних ключей на чужие таблицы нет — id
инвестпроекта, компании и автора хранятся как числа, чтобы таблицы создавались в любой
базе, где есть хотя бы пустая схема.

Создание и заполнение: ``python -m modules.deal_calculator.seed`` (см. docs/calculator.md).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CalcRegion(Base):
    """Регион или зона МОД3_Таб1 с коэффициентом.

    parent_code — уровень выше: район → область → зона.
    """

    __tablename__ = "calc_region"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    parent_code: Mapped[str | None] = mapped_column(String(32))
    coefficient: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    note: Mapped[str | None] = mapped_column(String(255))


class CalcPosition(Base):
    """Позиция каталога оборудования МОД3_Таб4: цена и коэффициент сложности."""

    __tablename__ = "calc_position"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    system_group: Mapped[str] = mapped_column(String(64))
    unit: Mapped[str] = mapped_column(String(32), default="шт.")
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    complexity_coef: Mapped[Decimal] = mapped_column(Numeric(5, 3), default=Decimal(1))
    price_period: Mapped[str | None] = mapped_column(String(16))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class CalcDictionary(Base):
    """Справочники МОД3: уровни проекта (Таб2), этапы работ (Таб3), схемы оплаты."""

    __tablename__ = "calc_dictionary"

    id: Mapped[int] = mapped_column(primary_key=True)
    dict_code: Mapped[str] = mapped_column(String(32), index=True)
    code: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(255))
    value: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    description: Mapped[str | None] = mapped_column(Text)
    order_no: Mapped[int] = mapped_column(Integer, default=0)


class CalcDeal(Base):
    """Прошлая сделка — аналог для вилки и пример для модели шанса выиграть."""

    __tablename__ = "calc_deal"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    # Отпечаток строки бандла: повторная загрузка не плодит дубли.
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    project_type: Mapped[str] = mapped_column(String(32), default="dispatching")
    object_type: Mapped[str | None] = mapped_column(String(32), index=True)
    scale: Mapped[str | None] = mapped_column(String(16))
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    project_level: Mapped[str | None] = mapped_column(String(16))
    region_code: Mapped[str | None] = mapped_column(String(32))
    cost_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    contract_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    outcome: Mapped[str | None] = mapped_column(String(8))  # won | lost
    retro_price_basis: Mapped[str] = mapped_column(String(16), default="synthetic")
    financing_scheme: Mapped[str | None] = mapped_column(String(32))
    payment_scheme: Mapped[str | None] = mapped_column(String(16))
    closed_at: Mapped[date | None] = mapped_column(Date)
    scope_json: Mapped[dict | None] = mapped_column(JSON)


class CalcEstimate(Base):
    """Расчёт калькулятора: вход, результат и утверждённая цена (ТЗ 8.3) — из него строится КП."""

    __tablename__ = "calc_estimate"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    author_id: Mapped[int | None] = mapped_column(Integer)
    investment_project_id: Mapped[int | None] = mapped_column(Integer, index=True)
    company_id: Mapped[int | None] = mapped_column(Integer)
    request_json: Mapped[dict] = mapped_column(JSON)
    price_min: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    price_optimum: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    price_max: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    cost_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    margin_min: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    margin_optimum: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    margin_max: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    win_probability: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    estimator_mode: Mapped[str] = mapped_column(String(16))
    optimum_method: Mapped[str | None] = mapped_column(String(32))
    data_quality: Mapped[str] = mapped_column(String(16))
    model_version: Mapped[str] = mapped_column(String(48))
    comparables_json: Mapped[list | None] = mapped_column(JSON)
    adjustments_json: Mapped[list | None] = mapped_column(JSON)
    cost_json: Mapped[dict | None] = mapped_column(JSON)
    curve_json: Mapped[list | None] = mapped_column(JSON)
    payment_json: Mapped[list | None] = mapped_column(JSON)
    approved_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    approved_by: Mapped[int | None] = mapped_column(Integer)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


CALC_TABLES = [CalcRegion.__table__, CalcPosition.__table__, CalcDictionary.__table__,
               CalcDeal.__table__, CalcEstimate.__table__]
