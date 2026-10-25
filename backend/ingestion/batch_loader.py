"""Bounded SQL batches with the same identifier/provenance rules as the seed loader."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import or_, select

from app.models import Company, CompanyMatch, CompanyMetric, SourceRecord
from ingestion.loader import SeedResult
from ingestion.normalize import (
    clean_revenue,
    is_valid_inn,
    is_valid_ogrn,
    match_key,
    normalize_name,
    payload_hash,
)


def load_company_batch(session, records, industry_ids, regions):
    """Import at most 1000 records; caller owns the transaction and batch boundaries."""
    if not 0 < len(records) <= 1000:
        raise ValueError("Company batch must contain 1..1000 records")
    result = SeedResult(source_records=len(records))
    payloads = [r.stable_payload() for r in records]
    digests = [payload_hash(p) for p in payloads]
    sources = {
        (s.source, s.payload_hash): s
        for s in session.scalars(
            select(SourceRecord)
            .where(
                SourceRecord.payload_hash.in_(set(digests)),
                SourceRecord.processing_status == "processed",
            )
            .order_by(SourceRecord.id.desc())
        )
    }
    for record, payload, digest in zip(records, payloads, digests, strict=True):
        key = (record.source, digest)
        if key not in sources:
            source = SourceRecord(
                source=record.source,
                external_id=record.external_id,
                payload_hash=digest,
                raw_payload=payload,
                processing_status="processed",
                fetched_at=datetime.now(UTC),
                license_note=record.license_note,
            )
            session.add(source)
            sources[key] = source
    session.flush()
    ordered_sources = [sources[(r.source, d)] for r, d in zip(records, digests, strict=True)]
    source_ids = {s.id for s in ordered_sources}
    matches = session.scalars(
        select(CompanyMatch).where(CompanyMatch.source_record_id.in_(source_ids))
    ).all()
    existing_pairs = {(m.company_id, m.source_record_id) for m in matches}
    inns = {r.inn for r in records if is_valid_inn(r.inn)}
    ogrns = {r.ogrn for r in records if is_valid_ogrn(r.ogrn)}
    companies = session.scalars(
        select(Company)
        .where(
            or_(
                Company.inn.in_(inns),
                Company.ogrn.in_(ogrns),
                Company.id.in_({m.company_id for m in matches}),
            )
        )
        .order_by(Company.id.desc())
    ).all()
    by_id = {c.id: c for c in companies}
    by_inn = {c.inn: c for c in companies if is_valid_inn(c.inn)}
    by_ogrn = {c.ogrn: c for c in companies if is_valid_ogrn(c.ogrn)}
    by_source = {m.source_record_id: by_id[m.company_id] for m in reversed(matches)}
    selected = []
    for record, source in zip(records, ordered_sources, strict=True):
        decision = match_key(record)
        company = by_source.get(source.id)
        if decision.method == "inn":
            candidate = by_inn.get(record.inn)
            if (
                candidate
                and is_valid_ogrn(candidate.ogrn)
                and is_valid_ogrn(record.ogrn)
                and candidate.ogrn != record.ogrn
            ):
                raise ValueError("Конфликт валидных идентификаторов компании; требуется проверка")
            company = company or candidate
        if company is None and is_valid_ogrn(record.ogrn):
            company = by_ogrn.get(record.ogrn)
            if (
                company
                and is_valid_inn(record.inn)
                and is_valid_inn(company.inn)
                and record.inn != company.inn
            ):
                raise ValueError("Конфликт ИНН при совпавшем ОГРН; требуется проверка")
        region = regions.get((record.region_code, record.municipality))
        industry = industry_ids.get(record.industry_code)
        if company is None:
            company = Company(
                name=record.name,
                name_normalized=normalize_name(record.name),
                inn=record.inn if is_valid_inn(record.inn) else None,
                ogrn=record.ogrn if is_valid_ogrn(record.ogrn) else None,
                industry_id=industry,
                region_id=region,
                employee_count=record.employee_count,
                client_status=record.client_status,
                first_seen_at=record.fetched_at,
                last_seen_at=record.fetched_at,
            )
            session.add(company)
            result.companies += 1
            if company.inn:
                by_inn[company.inn] = company
            if company.ogrn:
                by_ogrn[company.ogrn] = company
        else:
            result.skipped += 1
            if record.client_status == "active":
                company.client_status = "active"
            if company.employee_count is None:
                company.employee_count = record.employee_count
            if company.industry_id is None:
                company.industry_id = industry
            if company.region_id is None:
                company.region_id = region
        by_source[source.id] = company
        selected.append((record, source, company, decision))
    session.flush()
    revenue_rows = [(r, s, c, clean_revenue(r.revenue)) for r, s, c, _ in selected if r.revenue]
    metric_keys = (
        {
            (m.company_id, m.period_year, m.source_id)
            for m in session.scalars(
                select(CompanyMetric).where(
                    CompanyMetric.source_id.in_(source_ids), CompanyMetric.metric_code == "revenue"
                )
            )
        }
        if revenue_rows
        else set()
    )
    for _record, source, company, decision in selected:
        pair = (company.id, source.id)
        if pair not in existing_pairs:
            session.add(
                CompanyMatch(
                    company_id=company.id,
                    source_record_id=source.id,
                    match_method=decision.method,
                    confidence=Decimal(str(round(decision.confidence, 3))),
                )
            )
            existing_pairs.add(pair)
    for record, source, company, revenue in revenue_rows:
        for year, value in sorted(revenue.items()):
            key = (company.id, year, source.id)
            if key not in metric_keys:
                session.add(
                    CompanyMetric(
                        company_id=company.id,
                        metric_code="revenue",
                        period_year=year,
                        value=Decimal(str(value)),
                        unit="RUB mln",
                        source_id=source.id,
                        fetched_at=record.fetched_at,
                    )
                )
                metric_keys.add(key)
                result.metrics += 1
    session.flush()
    return (
        {d.company_key: c.id for _, _, c, d in selected},
        {(r.source, r.external_id): c.id for r, _, c, _ in selected},
        result,
    )
