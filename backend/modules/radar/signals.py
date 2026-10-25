"""Evidence-backed observations; a registry row does not prove federal expansion."""

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.persistence import insert
from app.models import Company, CompanyMatch, Industry, MarketEntrySignal, Region, SourceRecord
from modules.radar.companies import provenance


def detect_signals(session) -> int:
    codes = dict(session.execute(select(Region.code, Region.id)).all())
    seen = {}
    created = 0
    rows = session.execute(
        select(Company, SourceRecord, CompanyMatch.match_method)
        .join(CompanyMatch, CompanyMatch.company_id == Company.id)
        .join(SourceRecord, SourceRecord.id == CompanyMatch.source_record_id)
        .order_by(SourceRecord.fetched_at, SourceRecord.id)
    )
    for company, source, method in rows:
        payload = source.raw_payload or {}
        if provenance(source).is_synthetic:
            continue
        region_id = codes.get(payload.get("region_code"))
        if region_id is None or method != "inn" or payload.get("inn") != company.inn:
            continue
        previous = seen.setdefault(company.id, set())
        kinds = []
        if (payload.get("attributes") or {}).get("registry_new") is True:
            kinds.append(("new_registry_company", "Источник помечает компанию как вновь созданную"))
        if previous and region_id not in previous:
            kinds.append(
                (
                    "cross_region_observation",
                    "Один ИНН наблюдался в источниках разных регионов; "
                    "это сигнал для проверки, а не подтверждённое открытие подразделения",
                )
            )
        previous.add(region_id)
        for kind, evidence in kinds:
            if session.scalar(
                select(MarketEntrySignal.id).where(
                    MarketEntrySignal.company_id == company.id,
                    MarketEntrySignal.region_id == region_id,
                    MarketEntrySignal.signal_type == kind,
                )
            ):
                continue
            key = hashlib.sha256(f"{company.id}:{region_id}:{kind}".encode()).hexdigest()
            result = session.execute(
                insert(session, MarketEntrySignal)
                .values(
                    company_id=company.id,
                    region_id=region_id,
                    signal_type=kind,
                    event_key=key,
                    evidence=evidence,
                    source_id=source.id,
                    detected_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(index_elements=["event_key"])
            )
            created += result.rowcount
    return created


def insights(
    session,
    *,
    region_id=None,
    industry_group=None,
    municipality=None,
    signal_type=None,
    limit=50,
    offset=0,
):
    statement = (
        select(MarketEntrySignal, Company, SourceRecord)
        .join(Company, Company.id == MarketEntrySignal.company_id)
        .outerjoin(SourceRecord, SourceRecord.id == MarketEntrySignal.source_id)
    )
    if region_id is not None:
        statement = statement.where(MarketEntrySignal.region_id == region_id)
    if industry_group:
        statement = statement.where(
            Company.industry_id.in_(select(Industry.id).where(Industry.group == industry_group))
        )
    if municipality:
        statement = statement.where(Company.municipality == municipality)
    if signal_type:
        statement = statement.where(MarketEntrySignal.signal_type == signal_type)
    rows = session.execute(
        statement.order_by(MarketEntrySignal.detected_at.desc(), MarketEntrySignal.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        {
            "id": row.id,
            "company_id": company.id,
            "company_name": company.name,
            "inn": company.inn,
            "region_id": row.region_id,
            "signal_type": row.signal_type,
            "detected_at": row.detected_at,
            "evidence": row.evidence,
            "source_id": row.source_id,
            "provenance": provenance(source) if source else None,
            "confidence": "medium" if row.signal_type == "new_registry_company" else "low",
            "scoring_mode": "heuristic",
            "model_version": "market-signals-0.1",
            "is_synthetic": provenance(source).is_synthetic if source else False,
        }
        for row, company, source in rows
    ]
