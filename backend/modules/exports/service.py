"""Экспорт CSV/CRM и DOCX (модуль exports, раздел 12 ТЗ).

CSV: UTF-8 BOM, RFC 4180, русские заголовки, ISO-8601 для дат.
DOCX: редактируемый шаблон КП с дисклеймером и версией модели.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Deal, DealEstimate, Industry, ProposalExport, Region
from modules.radar import service as radar

# Маппинг задокументирован в docs/export-mapping.md — его требует критерий «Экспорт».
CSV_HEADERS = {
    "companies": {
        "id": "Идентификатор",
        "name": "Название",
        "inn": "ИНН",
        "client_status": "Статус клиента",
        "industry": "Отрасль",
        "region": "Регион",
        "revenue_latest": "Выручка, млн руб",
        "revenue_year": "Год выручки",
        "revenue_yoy": "Динамика выручки, %",
        "source_note": "Источник и дата",
    }
}
CRM_COLUMNS = ("externalId", "name", "inn", "industry", "region", "phone", "website")


def _status_label(status: str) -> str:
    return {"active": "действующий", "prospect": "потенциальный"}.get(status, "не определён")


def companies_rows(session: Session, filters: dict) -> list[dict]:
    companies = radar.list_companies(
        session,
        region_id=filters.get("region_id"),
        industry_id=filters.get("industry_id"),
        client_status=filters.get("client_status"),
        min_revenue=filters.get("min_revenue"),
        limit=filters.get("limit", 5000),
    )
    industries = dict(session.execute(select(Industry.id, Industry.name)).all())
    regions = dict(session.execute(select(Region.id, Region.name)).all())
    rows = []
    for c in companies:
        rows.append(
            {
                "id": c.id,
                "name": c.name,
                "inn": c.inn or "",
                "client_status": _status_label(c.client_status),
                "industry": industries.get(c.industry_id or -1, ""),
                "region": regions.get(c.region_id or -1, ""),
                "revenue_latest": c.revenue_latest if c.revenue_latest is not None else "",
                "revenue_year": c.revenue_year or "",
                "revenue_yoy": c.revenue_yoy if c.revenue_yoy is not None else "",
                # Пропуск остаётся пропуском: ноль вместо «нет данных» запрещён (ТЗ 6.8).
                "source_note": "демо-набор data/seed" if c.revenue_latest is None else "демо-набор data/seed",
            }
        )
    return rows


def to_csv(rows: list[dict], module: str, mode: str = "general") -> bytes:
    headers = CSV_HEADERS.get(module, {})
    buffer = io.StringIO()
    if mode == "crm":
        writer = csv.DictWriter(buffer, fieldnames=list(CRM_COLUMNS), quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "externalId": row.get("id", ""),
                    "name": row.get("name", ""),
                    "inn": row.get("inn", ""),
                    "industry": row.get("industry", ""),
                    "region": row.get("region", ""),
                    "phone": "",
                    "website": "",
                }
            )
    else:
        keys = list(headers) if headers else list(rows[0] if rows else [])
        writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
        writer.writerow([headers.get(k, k) for k in keys])
        for row in rows:
            writer.writerow([row.get(k, "") for k in keys])
    # BOM обязателен, иначе Excel открывает кириллицу кракозябрами.
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def build_proposal_docx(session: Session, estimate_id: int, author_id: int | None) -> str:
    from docx import Document

    estimate = session.get(DealEstimate, estimate_id)
    if estimate is None:
        raise ValueError("Оценка не найдена")
    deal = session.get(Deal, estimate.deal_id)
    params = (deal.input_params_json or {}) if deal else {}

    doc = Document()
    doc.add_heading("Коммерческое предложение (черновик)", level=1)
    doc.add_paragraph(
        f"Сформировано: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · "
        f"версия модели: {estimate.model_version}"
    )

    doc.add_heading("Параметры проекта", level=2)
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for key, value in params.items():
        row = table.add_row().cells
        row[0].text = key
        row[1].text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)

    doc.add_heading("Оценка стоимости", level=2)
    doc.add_paragraph(f"Минимум: {estimate.price_min:,.0f} руб.")
    doc.add_paragraph(f"Оптимум: {estimate.price_optimum:,.0f} руб.")
    doc.add_paragraph(f"Максимум: {estimate.price_max:,.0f} руб.")
    doc.add_paragraph(f"Метод расчёта: {estimate.estimator_mode}")
    doc.add_paragraph(f"Качество данных: {estimate.data_quality}")
    if estimate.price_period:
        doc.add_paragraph(f"Период ретро-цен: {estimate.price_period}")

    doc.add_heading("Аналоги", level=2)
    for comparable in estimate.comparables_json or []:
        doc.add_paragraph(
            f"{comparable.get('title')} — {comparable.get('contract_value'):,.0f} руб. "
            f"(сходство {comparable.get('similarity')})",
            style="List Bullet",
        )
    if not estimate.comparables_json:
        doc.add_paragraph("Аналоги не подобраны — оценка требует ручной проверки.")

    doc.add_heading("Поправки", level=2)
    for adjustment in estimate.adjustments_json or []:
        doc.add_paragraph(
            f"{adjustment.get('factor')}: {adjustment.get('value')}", style="List Bullet"
        )
    if not estimate.adjustments_json:
        doc.add_paragraph("Поправки не применялись.")

    doc.add_heading("Ограничения", level=2)
    doc.add_paragraph(
        "Документ создан автоматически на основе параметров, введённых пользователем, "
        "и ретро-данных указанного периода. Оценка требует проверки специалистом: "
        "окончательную стоимость сделки утверждает сотрудник."
    )

    out_dir = Path(get_settings().export_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"proposal-{estimate_id}-{stamp}.docx"
    doc.save(path)

    session.add(
        ProposalExport(deal_estimate_id=estimate_id, format="docx", file_ref=str(path), created_by=author_id)
    )
    return str(path)
