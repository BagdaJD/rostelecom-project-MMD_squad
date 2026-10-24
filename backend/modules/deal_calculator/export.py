"""Выгрузки калькулятора: CSV для Excel (расчёт, аналоги) и CSV для импорта в CRM.

* ``deals`` / ``comparables`` — для людей: UTF-8 с BOM, разделитель «;», десятичная запятая —
  русский Excel открывает файл по двойному щелчку сразу по колонкам;
* ``crm`` — для импорта: RFC 4180 (разделитель «,», десятичная точка), латинские поля.

Общий экспорт (modules/exports) не используется и не меняется.
"""

from __future__ import annotations

import csv
import io

from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.deal_calculator.models import CalcEstimate

DEAL_HEADERS = {
    "estimate_id": "Номер расчёта",
    "calculated_at": "Дата расчёта",
    "object": "Объект",
    "area_m2": "Площадь, м²",
    "region": "Регион",
    "project_level": "Уровень проекта",
    "points": "Приборов и контроллеров, шт",
    "cost_total": "Себестоимость, руб",
    "price_min": "Минимум, руб",
    "price_optimum": "Оптимум, руб",
    "price_max": "Максимум, руб",
    "margin_optimum": "Маржа при оптимуме, %",
    "win_probability": "Шанс выиграть, %",
    "approved_price": "Утверждённая цена, руб",
    "payment_scheme": "Схема оплаты",
    "analogs": "Аналогов",
    "estimator_mode": "Метод",
    "data_quality": "Качество данных",
    "model_version": "Версия модели",
}
COMPARABLE_HEADERS = {
    "estimate_id": "Номер расчёта",
    "deal_id": "Идентификатор сделки",
    "title": "Сделка",
    "similarity": "Сходство, %",
    "contract_value": "Цена, руб",
    "cost_value": "Себестоимость, руб",
    "price_index": "Наценка",
    "outcome": "Итог",
    "retro_price_basis": "Источник",
}
CRM_DEAL_COLUMNS = ("externalId", "title", "amount", "currency", "stage", "companyName", "inn",
                    "source", "comment")
LEVEL_LABELS = {"basic": "Базовый", "advanced": "Продвинутый", "expert": "Экспертный"}
PAYMENT_LABELS = {"capex": "Единовременно", "installment": "Рассрочка", "opex": "Сервис"}
METHOD_LABELS = {"hybrid": "аналоги + модель шанса", "rule_based": "по себестоимости",
                 "analogs": "по аналогам"}
QUALITY_LABELS = {"sufficient": "достаточно аналогов", "limited": "мало аналогов",
                  "insufficient": "аналогов нет"}
BASIS_LABELS = {"contract": "контракт ЕИС", "estimate": "оценка", "synthetic": "демо"}
BOM = b"\xef\xbb\xbf"  # без него Excel открывает кириллицу кракозябрами


def _num(value) -> float | str:
    return "" if value is None else round(float(value), 2)


def _excel(value) -> str:
    """Ячейка для русского Excel: десятичная запятая, целые без «,0»."""
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}".rstrip("0").replace(".", ",")
    return "" if value is None else str(value)


def _estimates(session: Session, estimate_id: int | None, limit: int = 500) -> list[CalcEstimate]:
    stmt = select(CalcEstimate).order_by(CalcEstimate.id.desc())
    if estimate_id:
        stmt = stmt.where(CalcEstimate.id == estimate_id)
    return list(session.scalars(stmt.limit(limit)))


def deal_rows(session: Session, estimate_id: int | None) -> list[dict]:
    rows = []
    for e in _estimates(session, estimate_id):
        params = e.request_json or {}
        cost = e.cost_json or {}
        rows.append({
            "estimate_id": e.id,
            "calculated_at": e.created_at.date().isoformat() if e.created_at else "",
            "object": cost.get("object_label") or "",
            "area_m2": _num(cost.get("area_m2")),
            "region": cost.get("region_label") or "",
            "project_level": LEVEL_LABELS.get(params.get("project_level"), ""),
            "points": _num(cost.get("points")),
            "cost_total": _num(e.cost_total),
            "price_min": _num(e.price_min),
            "price_optimum": _num(e.price_optimum),
            "price_max": _num(e.price_max),
            "margin_optimum": _num(e.margin_optimum),
            "win_probability": _num(e.win_probability),
            "approved_price": _num(e.approved_price),
            "payment_scheme": PAYMENT_LABELS.get(params.get("payment_scheme"), ""),
            "analogs": len(e.comparables_json or []),
            "estimator_mode": METHOD_LABELS.get(e.estimator_mode, e.estimator_mode),
            "data_quality": QUALITY_LABELS.get(e.data_quality, e.data_quality),
            "model_version": e.model_version,
        })
    return rows


def comparable_rows(session: Session, estimate_id: int | None) -> list[dict]:
    rows = []
    for e in _estimates(session, estimate_id):
        for c in e.comparables_json or []:
            rows.append({
                "estimate_id": e.id,
                "deal_id": c.get("deal_id", ""),
                "title": c.get("title", ""),
                "similarity": _num((c.get("similarity") or 0) * 100),
                "contract_value": _num(c.get("contract_value")),
                "cost_value": _num(c.get("cost_value")),
                "price_index": _num(c.get("price_index")),
                "outcome": {"won": "выиграли", "lost": "проиграли"}.get(c.get("outcome"), ""),
                "retro_price_basis": BASIS_LABELS.get(c.get("retro_price_basis"),
                                                      c.get("retro_price_basis", "")),
            })
    return rows


def excel_csv(rows: list[dict], headers: dict[str, str]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(headers.values())
    for row in rows:
        writer.writerow([_excel(row.get(k, "")) for k in headers])
    return BOM + buffer.getvalue().encode("utf-8")


def crm_csv(session: Session, estimate_id: int | None) -> bytes:
    """Сделка для импорта в CRM: сумма — утверждённая цена или оптимум расчёта."""
    from app.models import Company

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(CRM_DEAL_COLUMNS))
    writer.writeheader()
    for e in _estimates(session, estimate_id):
        cost = e.cost_json or {}
        company = None
        if e.company_id:
            try:
                company = session.get(Company, e.company_id)
            except Exception:  # noqa: BLE001 — таблицы компаний может не быть
                session.rollback()
        writer.writerow({
            "externalId": f"rtk-calc-{e.id}",
            "title": f"Диспетчеризация: {cost.get('object_label') or ''}".strip(": "),
            "amount": float(e.approved_price or e.price_optimum),
            "currency": "RUB",
            "stage": "Утверждено" if e.approved_price else "Расчёт",
            "companyName": company.name if company else "",
            "inn": (company.inn or "") if company else "",
            "source": "Калькулятор сделок",
            "comment": f"Вилка {_num(e.price_min)}–{_num(e.price_max)} руб; "
                       f"маржа {_num(e.margin_optimum)}%",
        })
    return BOM + buffer.getvalue().encode("utf-8")


def export_csv(session: Session, kind: str, estimate_id: int | None) -> bytes:
    if kind == "deals":
        return excel_csv(deal_rows(session, estimate_id), DEAL_HEADERS)
    if kind == "comparables":
        return excel_csv(comparable_rows(session, estimate_id), COMPARABLE_HEADERS)
    if kind == "crm":
        return crm_csv(session, estimate_id)
    raise ValueError(f"Неизвестная выгрузка: {kind}")
