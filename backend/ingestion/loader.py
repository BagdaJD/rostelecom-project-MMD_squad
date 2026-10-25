"""Загрузка демо-набора в БД: идемпотентно и с provenance (этап 2 плана).

Идемпотентность проверяется тестом: повторный импорт не создаёт дублей.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from geoalchemy2 import WKTElement
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    CompanyMatch,
    CompanyMetric,
    CustomerPresence,
    DictionaryItem,
    HistoricalDeal,
    Industry,
    InvestmentEvent,
    InvestmentProject,
    OkvedToIndustry,
    PositionPrice,
    ProjectTender,
    Region,
    RegionalCoefficient,
    SourceRecord,
    Tender,
)
from ingestion.normalize import (
    RawCompany,
    clean_revenue,
    is_valid_inn,
    is_valid_ogrn,
    match_key,
    normalize_name,
    payload_hash,
)
from ml.needs import classify_need
from ml.storage import replace_needs

STAGES = ("design", "modernization", "construction", "launch", "completed")
NEED_DICT = "project_need"
STAGE_DICT = "project_stage"

DICTIONARIES: dict[str, list[tuple[str, str]]] = {
    STAGE_DICT: [
        ("design", "Проектирование"),
        ("modernization", "Модернизация"),
        ("construction", "Строительство"),
        ("launch", "Ввод в эксплуатацию"),
        ("completed", "Завершён"),
        ("unknown", "Стадия не подтверждена"),
    ],
    NEED_DICT: [
        ("connectivity", "Связь и каналы передачи данных"),
        ("it_infrastructure", "ИТ-инфраструктура и ЦОД"),
        ("information_security", "Информационная безопасность"),
        ("video_surveillance", "Видеонаблюдение"),
        ("iot_asu_tp", "IoT и АСУ ТП"),
        ("insufficient_data", "Недостаточно данных"),
    ],
    "urgency": [
        ("normal", "Стандартные сроки"),
        ("high", "Сжатые сроки"),
        ("critical", "Критично"),
    ],
    "financing_scheme": [
        ("budget", "Бюджетное финансирование"),
        ("own", "Собственные средства"),
        ("lease", "Лизинг"),
        ("concession", "Концессия"),
    ],
}


@dataclass
class SeedResult:
    regions: int = 0
    industries: int = 0
    companies: int = 0
    metrics: int = 0
    projects: int = 0
    projects_updated: int = 0
    tenders: int = 0
    tenders_updated: int = 0
    links: int = 0
    presence: int = 0
    deals: int = 0
    skipped: int = 0
    source_records: int = 0

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _source(
    session: Session,
    source: str,
    external_id: str | None,
    payload: dict,
    license_note: str | None = None,
) -> SourceRecord:
    """Одна запись происхождения на объект; повторный импорт узнаётся по hash."""
    digest = payload_hash({k: v for k, v in payload.items() if k != "fetched_at"})
    existing = session.scalar(
        select(SourceRecord).where(
            SourceRecord.source == source,
            SourceRecord.external_id == external_id,
            SourceRecord.payload_hash == digest,
            SourceRecord.processing_status == "processed",
        )
    )
    if existing:
        return existing
    record = SourceRecord(
        source=source,
        external_id=external_id,
        payload_hash=digest,
        raw_payload=payload,
        processing_status="processed",
        fetched_at=datetime.now(UTC),
        license_note=license_note,
    )
    session.add(record)
    session.flush()
    return record


def load_dictionaries(session: Session) -> int:
    created = 0
    for dict_code, items in DICTIONARIES.items():
        for order_no, (code, label) in enumerate(items):
            exists = session.scalar(
                select(DictionaryItem).where(
                    DictionaryItem.dict_code == dict_code, DictionaryItem.code == code
                )
            )
            if exists:
                continue
            session.add(
                DictionaryItem(dict_code=dict_code, code=code, label=label, order_no=order_no)
            )
            created += 1
    return created


def load_regions(session: Session, rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        region = session.scalar(select(Region).where(Region.code == row["code"]))
        if region is None:
            region = Region(name=row["name"], code=row["code"])
            if row.get("wkt"):
                region.geometry = WKTElement(row["wkt"], srid=4326)
            center = row.get("center") or []
            if len(center) == 2:
                region.center_lon = Decimal(str(center[0]))
                region.center_lat = Decimal(str(center[1]))
            session.add(region)
            session.flush()
        out[row["code"]] = region.id
    return out


def load_industries(session: Session, rows: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    by_code: dict[str, int] = {}
    okved: dict[str, int] = {}
    for row in rows:
        industry = session.scalar(select(Industry).where(Industry.code == row["code"]))
        if industry is None:
            industry = Industry(code=row["code"], name=row["name"], group=row["group"])
            session.add(industry)
            session.flush()
        by_code[row["code"]] = industry.id
        for code in row.get("okved", []):
            okved[code] = industry.id
            if not session.scalar(
                select(OkvedToIndustry).where(
                    OkvedToIndustry.okved_code == code, OkvedToIndustry.industry_id == industry.id
                )
            ):
                session.add(OkvedToIndustry(okved_code=code, industry_id=industry.id))
    return by_code, okved


def load_companies(
    session: Session,
    records: list[RawCompany],
    industry_by_okved: dict[str, int],
    region_codes: dict[str, int],
) -> tuple[dict[str, int], SeedResult]:
    """Возвращает company_key → id; повторная загрузка тех же данных ничего не добавляет."""
    result = SeedResult()
    keys: dict[str, int] = {}
    for record in records:
        source = _source(
            session, record.source, record.external_id, record.stable_payload(), record.license_note
        )
        result.source_records += 1
        decision = match_key(record)
        company = session.scalar(
            select(Company)
            .join(CompanyMatch, CompanyMatch.company_id == Company.id)
            .where(CompanyMatch.source_record_id == source.id)
        )
        if decision.method == "inn" and record.inn:
            by_inn = session.scalars(select(Company).where(Company.inn == record.inn)).first()
            if (
                by_inn
                and is_valid_ogrn(by_inn.ogrn)
                and is_valid_ogrn(record.ogrn)
                and (by_inn.ogrn != record.ogrn)
            ):
                raise ValueError("Конфликт валидных идентификаторов компании; требуется проверка")
            company = company or by_inn
        if company is None and is_valid_ogrn(record.ogrn):
            by_ogrn = session.scalars(select(Company).where(Company.ogrn == record.ogrn)).first()
            if (
                by_ogrn
                and is_valid_inn(record.inn)
                and is_valid_inn(by_ogrn.inn)
                and (record.inn != by_ogrn.inn)
            ):
                raise ValueError("Конфликт ИНН при совпавшем ОГРН; требуется проверка")
            company = by_ogrn

        if company is None:
            company = Company(
                name=record.name,
                name_normalized=normalize_name(record.name),
                inn=record.inn if is_valid_inn(record.inn) else None,
                ogrn=record.ogrn if is_valid_ogrn(record.ogrn) else None,
                industry_id=industry_by_okved.get(record.industry_code or ""),
                region_id=region_codes.get(record.region_code or ""),
                employee_count=record.employee_count,
                source_id=source.id,
                client_status=record.client_status,
                first_seen_at=record.fetched_at,
                last_seen_at=record.fetched_at,
            )
            session.add(company)
            session.flush()
            result.companies += 1
        else:
            result.skipped += 1

        synthetic = (
            record.is_synthetic or record.source == "demo" or record.source.startswith("synthetic")
        )
        if company.source_id in (None, source.id) or company.is_synthetic or not synthetic:
            company.name = record.name
            company.name_normalized = normalize_name(record.name)
            industry = industry_by_okved.get(record.industry_code or "")
            company.industry_id = industry or company.industry_id
            company.region_id = region_codes.get(record.region_code or "") or company.region_id
            company.employee_count = record.employee_count
            company.municipality = record.municipality
            company.city = record.city
            company.settlement = record.settlement
            company.source_id = source.id
            company.is_synthetic = synthetic
            company.attributes_json = record.attributes
        if record.client_status == "active" or company.client_status == "unknown":
            company.client_status = record.client_status
        company.last_seen_at = record.fetched_at

        if not session.scalar(
            select(CompanyMatch.id).where(
                CompanyMatch.company_id == company.id,
                CompanyMatch.source_record_id == source.id,
            )
        ):
            session.add(
                CompanyMatch(
                    company_id=company.id,
                    source_record_id=source.id,
                    match_method=decision.method,
                    confidence=Decimal(str(round(decision.confidence, 3))),
                )
            )
        for year, value in sorted(clean_revenue(record.revenue).items()):
            exists = session.scalar(
                select(CompanyMetric).where(
                    CompanyMetric.company_id == company.id,
                    CompanyMetric.metric_code == "revenue",
                    CompanyMetric.period_year == year,
                    CompanyMetric.source_id == source.id,
                )
            )
            if exists:
                continue
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
            result.metrics += 1
        keys[decision.company_key] = company.id
        session.flush()
    return keys, result


def load_projects(
    session: Session,
    rows: list[dict],
    region_codes: dict[str, int],
    industry_codes: dict[str, int],
    company_ids: dict[str, int],
    model_version: str,
) -> SeedResult:
    result = SeedResult()
    for row in rows:
        source = _source(session, row.get("source", "investregistry"), row.get("external_id"), row)
        result.source_records += 1
        existing = (
            session.scalar(
                select(InvestmentProject)
                .join(SourceRecord, SourceRecord.id == InvestmentProject.source_id)
                .where(
                    SourceRecord.source == source.source,
                    SourceRecord.external_id == source.external_id,
                )
            )
            if source.external_id
            else None
        )
        if existing is None:
            existing = session.scalar(
                select(InvestmentProject).where(InvestmentProject.title == row["title"])
            )
        if existing and existing.source_id == source.id:
            result.skipped += 1
            continue
        fields = dict(
            title=row["title"],
            description=row.get("description"),
            stage=row["stage"],
            planned_start=date.fromisoformat(row["planned_start"])
            if row.get("planned_start")
            else None,
            planned_end=date.fromisoformat(row["planned_end"]) if row.get("planned_end") else None,
            estimated_budget=Decimal(str(row["estimated_budget"]))
            if row.get("estimated_budget") is not None
            else None,
            region_id=region_codes.get(row.get("region_code") or ""),
            industry_id=industry_codes.get(row.get("industry_code") or ""),
            initiator_company_id=company_ids.get(row.get("initiator_key") or ""),
            source_url=row.get("source_url"),
            source_id=source.id,
            confidence=Decimal(str(row.get("confidence", 0.8))),
            is_synthetic=bool(
                row.get(
                    "is_synthetic", row.get("source_url", "").startswith("https://example.com/")
                )
            ),
        )
        if existing is None:
            project = InvestmentProject(**fields)
            session.add(project)
            result.projects += 1
        else:
            project = existing
            for key, value in fields.items():
                setattr(project, key, value)
            result.projects_updated += 1
        session.flush()
        from modules.investments.service import refresh_needs
        from modules.notifications.events import project_event

        project_event(session, project, created=existing is None)
        refresh_needs(session, project, model_version)

        session.add(
            InvestmentEvent(
                event_date=project.planned_start or date.today(),
                event_type=f"stage:{project.stage}",
                project_id=project.id,
                region_id=project.region_id,
                industry_id=project.industry_id,
                title=project.title,
            )
        )
        replace_needs(session, project.id, classify_need(project.title, project.description))
    return result


def load_tenders(
    session: Session, rows: list[dict], company_ids: dict[str, int], project_titles: dict[str, int]
) -> SeedResult:
    result = SeedResult()
    for row in rows:
        source = _source(session, row.get("source", "eis"), row.get("external_id"), row)
        result.source_records += 1
        existing = session.scalar(select(Tender).where(Tender.external_id == row["external_id"]))
        if existing and existing.source_id == source.id:
            result.skipped += 1
            continue
        fields = dict(
            external_id=row["external_id"],
            title=row["title"],
            description=row.get("description"),
            price=Decimal(str(row["price"])) if row.get("price") is not None else None,
            publication_date=date.fromisoformat(row["publication_date"])
            if row.get("publication_date")
            else None,
            deadline_date=date.fromisoformat(row["deadline_date"])
            if row.get("deadline_date")
            else None,
            category=row.get("category"),
            source_url=row.get("source_url"),
            source_id=source.id,
            customer_company_id=company_ids.get(row.get("customer_key") or ""),
            status=row.get("status", "published"),
        )
        if existing is None:
            tender = Tender(**fields)
            session.add(tender)
            result.tenders += 1
        else:
            tender = existing
            for key, value in fields.items():
                setattr(tender, key, value)
            result.tenders_updated += 1
        session.flush()
        from modules.notifications.events import tender_event

        tender_event(session, tender, created=existing is None)

        project_id = project_titles.get(row.get("project_title") or "")
        if project_id and not session.scalar(
            select(ProjectTender.project_id).where(
                ProjectTender.project_id == project_id, ProjectTender.tender_id == tender.id
            )
        ):
            session.add(
                ProjectTender(
                    project_id=project_id,
                    tender_id=tender.id,
                    # Способ связи сохраняется: внешняя ссылка и ИНН — разные основания.
                    link_method=row.get("link_method", "inn_keyword"),
                    confidence=Decimal(str(row.get("link_confidence", 0.7))),
                )
            )
            result.links += 1
    return result


def load_presence(session: Session, rows: list[dict], region_codes: dict[str, int]) -> SeedResult:
    result = SeedResult()
    for row in rows:
        region_id = region_codes.get(row.get("region_code") or "")
        exists = session.scalar(
            select(CustomerPresence).where(
                CustomerPresence.region_id == region_id,
                CustomerPresence.service_type == row["service_type"],
                CustomerPresence.as_of_date == date.fromisoformat(row["as_of_date"]),
            )
        )
        if exists or not region_id:
            result.skipped += 1
            continue
        source = _source(
            session, "synthetic_presence", None, row, "синтетические данные присутствия"
        )
        session.add(
            CustomerPresence(
                region_id=region_id,
                municipality=row.get("municipality"),
                service_type=row["service_type"],
                coverage_percent=Decimal(str(row.get("coverage_percent", 0))),
                contracts_count=row.get("contracts_count", 0),
                as_of_date=date.fromisoformat(row["as_of_date"]),
                source_id=source.id,
                is_synthetic=True,
            )
        )
        result.presence += 1
    return result


def load_reference_prices(session: Session, rows: list[dict]) -> SeedResult:
    result = SeedResult()
    for row in rows:
        if session.scalar(select(PositionPrice).where(PositionPrice.name == row["name"])):
            result.skipped += 1
            continue
        source = _source(session, "synthetic_prices", row.get("name"), row, "синтетический прайс")
        session.add(
            PositionPrice(
                name=row["name"],
                category=row.get("category", "equipment"),
                unit=row.get("unit", "шт"),
                price_min=Decimal(str(row["price_min"])) if row.get("price_min") else None,
                price_max=Decimal(str(row["price_max"])) if row.get("price_max") else None,
                price_typical=Decimal(str(row["price_typical"]))
                if row.get("price_typical")
                else None,
                price_period=row.get("price_period"),
                source_id=source.id,
                is_synthetic=True,
            )
        )
        result.presence += 0
    return result


def load_coefficients(
    session: Session, rows: list[dict], region_codes: dict[str, int]
) -> SeedResult:
    result = SeedResult()
    for row in rows:
        region_id = region_codes.get(row.get("region_code") or "")
        if not region_id:
            continue
        if session.scalar(
            select(RegionalCoefficient).where(
                RegionalCoefficient.region_id == region_id,
                RegionalCoefficient.work_type == row["work_type"],
            )
        ):
            result.skipped += 1
            continue
        session.add(
            RegionalCoefficient(
                region_id=region_id,
                work_type=row["work_type"],
                coefficient=Decimal(str(row["coefficient"])),
                effective_from=date.fromisoformat(row.get("effective_from", "2026-01-01")),
            )
        )
    return result


def load_historical_deals(
    session: Session, rows: list[dict], region_codes: dict[str, int], industry_codes: dict[str, int]
) -> SeedResult:
    result = SeedResult()
    for row in rows:
        if session.scalar(select(HistoricalDeal).where(HistoricalDeal.title == row["title"])):
            result.skipped += 1
            continue
        session.add(
            HistoricalDeal(
                title=row["title"],
                project_type=row["project_type"],
                scale=row.get("scale"),
                scope_json=row.get("scope") or {},
                region_id=region_codes.get(row.get("region_code") or ""),
                industry_id=industry_codes.get(row.get("industry_code") or ""),
                contract_value=Decimal(str(row["contract_value"])),
                retro_price_basis=row.get("retro_price_basis", "synthetic"),
                financing_scheme=row.get("financing_scheme"),
                closed_at=date.fromisoformat(row["closed_at"]) if row.get("closed_at") else None,
            )
        )
        result.deals += 1
    return result


def load_bundle(session: Session, bundle: dict, model_version: str = "seed-0.1") -> SeedResult:
    total = SeedResult()
    load_dictionaries(session)
    region_codes = load_regions(session, bundle.get("regions", []))
    industry_codes, okved = load_industries(session, bundle.get("industries", []))

    companies = [RawCompany(**row) for row in bundle.get("companies", [])]
    company_ids, res = load_companies(session, companies, okved, region_codes)
    _merge(total, res)

    projects = bundle.get("projects", [])
    _merge(
        total,
        load_projects(session, projects, region_codes, industry_codes, company_ids, model_version),
    )
    title_ids = {
        t: pid
        for t, pid in session.execute(select(InvestmentProject.title, InvestmentProject.id)).all()
    }
    _merge(total, load_tenders(session, bundle.get("tenders", []), company_ids, title_ids))
    _merge(total, load_presence(session, bundle.get("presence", []), region_codes))
    _merge(total, load_coefficients(session, bundle.get("coefficients", []), region_codes))
    load_reference_prices(session, bundle.get("positions", []))
    _merge(
        total,
        load_historical_deals(
            session, bundle.get("historical_deals", []), region_codes, industry_codes
        ),
    )
    session.flush()
    from modules.radar.signals import detect_signals
    from modules.readmodels.service import mark_changed

    detect_signals(session)
    mark_changed(session)
    return total


def _merge(target: SeedResult, other: SeedResult) -> None:
    for key, value in other.__dict__.items():
        setattr(target, key, getattr(target, key) + value)


def read_bundle(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
