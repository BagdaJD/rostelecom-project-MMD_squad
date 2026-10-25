from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    CompanyMatch,
    CustomerPresence,
    InvestmentProject,
    SourceRecord,
    Tender,
)
from app.schemas import CompanyOut
from app.schemas.companies import CompanyCardOut, MetricOut, ProvenanceOut
from modules.investments.service import project_view
from modules.radar.metrics import financials, metrics_for_company


def provenance(record: SourceRecord) -> ProvenanceOut:
    payload = record.raw_payload or {}
    attributes = payload.get("attributes") or {}
    location = payload.get("provenance") or attributes.get("provenance") or {}
    return ProvenanceOut(
        id=record.id,
        source=record.source,
        external_id=record.external_id,
        fetched_at=record.fetched_at,
        license_note=record.license_note,
        source_url=payload.get("source_url"),
        source_file=location.get("file"),
        sheet=location.get("sheet"),
        row=location.get("row"),
        is_synthetic=record.source == "demo"
        or record.source.startswith("synthetic")
        or payload.get("is_synthetic") is True,
    )


def company_card(session: Session, company_id: int) -> CompanyCardOut | None:
    company = session.get(Company, company_id)
    if company is None:
        return None
    data = CompanyOut.model_validate(company).model_dump()
    numbers = financials()
    financial = (
        session.execute(select(numbers).where(numbers.c.company_id == company_id))
        .mappings()
        .first()
    )
    if financial:
        data.update(
            {
                key: financial[key]
                for key in ("revenue_year", "revenue_latest", "revenue_yoy", "revenue_is_synthetic")
            }
        )
    projects = session.scalars(
        select(InvestmentProject)
        .where(InvestmentProject.initiator_company_id == company_id)
        .order_by(InvestmentProject.id)
    ).all()
    sources = session.scalars(
        select(SourceRecord)
        .where(
            SourceRecord.id.in_(
                select(CompanyMatch.source_record_id).where(CompanyMatch.company_id == company_id)
            )
        )
        .order_by(SourceRecord.fetched_at.desc(), SourceRecord.id.desc())
    ).all()
    if company.source_id and all(source.id != company.source_id for source in sources):
        record = session.get(SourceRecord, company.source_id)
        if record:
            sources = [record, *sources]
    rows = session.scalars(
        select(CustomerPresence)
        .where(
            CustomerPresence.region_id == company.region_id,
            CustomerPresence.as_of_date <= date.today(),
        )
        .order_by(CustomerPresence.as_of_date.desc(), CustomerPresence.id.desc())
    ).all()
    latest = {}
    for row in rows:
        latest.setdefault((row.municipality, row.service_type), row)
    signals = [f"Инвестиционный проект: {p.title}" for p in projects if p.stage != "completed"]
    tenders = session.scalars(
        select(Tender).where(
            Tender.customer_company_id == company_id,
            Tender.deadline_date >= date.today(),
            Tender.status == "published",
        )
    ).all()
    signals.extend(f"Открытая закупка: {t.title}" for t in tenders)
    warnings = []
    if data["revenue_latest"] is None:
        warnings.append("Выручка не представлена в доступных источниках")
    if data["revenue_is_synthetic"]:
        warnings.append("Финансовые показатели используют синтетические данные")
    if latest:
        warnings.append("Региональное присутствие услуг не подтверждает контракт этой компании")
    return CompanyCardOut(
        **data,
        ogrn=company.ogrn,
        employee_count=company.employee_count,
        metrics=[
            MetricOut.model_validate(dict(row)) for row in metrics_for_company(session, company_id)
        ],
        presence=[
            {
                "region_id": p.region_id,
                "municipality": p.municipality,
                "service_type": p.service_type,
                "coverage_percent": p.coverage_percent,
                "contracts_count": p.contracts_count,
                "as_of_date": p.as_of_date,
                "is_synthetic": p.is_synthetic,
                "source_id": p.source_id,
            }
            for p in latest.values()
        ],
        provenance=[provenance(source) for source in sources],
        demand_signals=signals,
        projects=[project_view(p) for p in projects],
        attributes=company.attributes_json or {},
        warnings=warnings,
    )
