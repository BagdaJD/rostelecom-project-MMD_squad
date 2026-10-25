"""Импорт в имеющиеся сущности SQLAlchemy; транзакцией управляет вызывающий код."""

from datetime import date
from decimal import Decimal
from itertools import batched

from sqlalchemy import select

from app.models import (
    Industry,
    InvestmentProject,
    Region,
    ScoringSnapshot,
    SourceRecord,
)
from ingestion.batch_loader import load_company_batch
from ingestion.features import industry_for_okved
from ingestion.loader import _source
from ingestion.normalize import RawCompany, match_key, payload_hash
from ml.storage import replace_needs

INDUSTRY_NAMES = {
    "agriculture": "АПК",
    "industry": "Промышленность",
    "energy": "ТЭК",
    "trade": "Торговля",
    "logistics": "Логистика и склады",
    "services": "Услуги",
    "housing": "Строительство и недвижимость",
    "unknown": "Отрасль не определена",
}


def _regions(session, rows):
    mapping = {}
    for row in rows:
        code = row.get("region_code")
        if not code:
            continue
        if (code, row.get("municipality")) in mapping:
            continue
        region = (
            session.get(Region, mapping[(code, None)])
            if (code, None) in mapping
            else (session.scalar(select(Region).where(Region.code == code)))
        )
        if not region:
            region = Region(
                code=code, name="Ростовская область" if code == "61" else f"Регион {code}"
            )
            session.add(region)
            session.flush()
        mapping[(code, None)] = region.id
        municipality = row.get("municipality")
        if municipality:
            local_code = code + ":" + payload_hash(municipality)[:16]
            local = session.scalar(select(Region).where(Region.code == local_code))
            if not local:
                local = Region(code=local_code, name=municipality, parent_id=region.id)
                session.add(local)
                session.flush()
            mapping[(code, municipality)] = local.id
    return mapping


def _snapshot(session, subject_type, subject_id, result, *, industry=None):
    # История хранится только при изменении входа/результата, повторный импорт идемпотентен.
    payload = {**result, "industry": industry}
    existing = session.scalars(
        select(ScoringSnapshot)
        .where(
            ScoringSnapshot.subject_type == subject_type,
            ScoringSnapshot.subject_id == subject_id,
            ScoringSnapshot.model_version == result["model_version"],
        )
        .order_by(ScoringSnapshot.id.desc())
    ).all()
    if any(s.factors_json == [payload] for s in existing):
        return
    session.add(
        ScoringSnapshot(
            subject_type=subject_type,
            subject_id=subject_id,
            score=result.get("score", result.get("potential_score")),
            factors_json=[payload],
            scoring_mode="heuristic",
            model_version=result["model_version"],
        )
    )
    session.flush()


def _company_snapshots(session, rows, company_ids, source_company_ids, fields):
    for batch in batched(rows, 1000):
        pending = []
        for row in batch:
            record = RawCompany(**{k: v for k, v in row.items() if k in fields})
            decision = match_key(record)
            cid = (
                company_ids.get(decision.company_key)
                if decision.method in ("inn", "ogrn")
                else source_company_ids.get((record.source, record.external_id))
            )
            if cid is not None:
                pending.append((cid, row["scoring"]))
        existing = {}
        for snapshot in session.scalars(
            select(ScoringSnapshot).where(
                ScoringSnapshot.subject_type == "company",
                ScoringSnapshot.subject_id.in_({cid for cid, _ in pending}),
                ScoringSnapshot.model_version.in_({r["model_version"] for _, r in pending}),
            )
        ):
            existing.setdefault((snapshot.subject_id, snapshot.model_version), []).append(
                snapshot.factors_json
            )
        for cid, result in pending:
            payload = [{**result, "industry": None}]
            key = (cid, result["model_version"])
            if payload in existing.get(key, []):
                continue
            session.add(
                ScoringSnapshot(
                    subject_type="company",
                    subject_id=cid,
                    score=result.get("score"),
                    factors_json=payload,
                    scoring_mode="heuristic",
                    model_version=result["model_version"],
                )
            )
            existing.setdefault(key, []).append(payload)
        session.flush()


def import_result(session, data: dict, *, batch_size: int = 1000) -> dict:
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    if data.get("format_version") != "mmd-pipeline-1":
        raise ValueError("Ожидается normalized.json pipeline версии 1")
    sources = data.get("source_records") or data["companies"]
    regions = _regions(session, [*sources, *data["projects"]])
    industry_ids = {}
    for code, name in INDUSTRY_NAMES.items():
        industry = session.scalar(select(Industry).where(Industry.code == code))
        if industry is None:
            industry = Industry(code=code, name=name, group=code)
            session.add(industry)
            session.flush()
        industry_ids[code] = industry.id
    fields = RawCompany.__dataclass_fields__
    company_ids = {}
    source_company_ids = {}
    created = 0
    for batch in batched(sources, batch_size):
        records = [RawCompany(**{k: v for k, v in row.items() if k in fields}) for row in batch]
        mapping, source_mapping, stats = load_company_batch(
            session,
            records,
            {
                r.industry_code: industry_ids.get(industry_for_okved(r.industry_code))
                for r in records
            },
            regions,
        )
        company_ids.update(mapping)
        source_company_ids.update(source_mapping)
        created += stats.companies
    _company_snapshots(session, data["companies"], company_ids, source_company_ids, fields)
    project_count = 0
    for row in data["projects"]:
        # Идентичность проекта — источник и внешний ID, а не одно название.
        source = _source(
            session,
            row["source"],
            row["external_id"],
            {k: v for k, v in row.items() if k != "recommendations"},
        )
        project = session.scalar(
            select(InvestmentProject)
            .join(SourceRecord, SourceRecord.id == InvestmentProject.source_id)
            .where(
                SourceRecord.source == row["source"], SourceRecord.external_id == row["external_id"]
            )
        )
        if project is None:
            project = InvestmentProject(title=row["title"], stage=row.get("stage") or "unknown")
            session.add(project)
            project_count += 1
        project.description = row.get("description")
        project.source_id = source.id
        project.source_url = row.get("source_url")
        project.region_id = regions.get((row.get("region_code"), row.get("municipality")))
        project.industry_id = industry_ids.get(row.get("industry"))
        # Бюджет Excel в млн руб; в БД — рубли. Это общий бюджет проекта, не услуг.
        budget = row.get("investment_mln_rub")
        project.estimated_budget = Decimal(str(budget)) * 1_000_000 if budget is not None else None
        project.confidence = None
        project.planned_start = (
            date.fromisoformat(row["planned_start"]) if row.get("planned_start") else None
        )
        project.planned_end = (
            date.fromisoformat(row["planned_end"]) if row.get("planned_end") else None
        )
        # Вероятное совпадение по имени хранится только в исходном payload; FK не назначается.
        decision = row.get("company_match") or {}
        if decision.get("status") == "matched" and len(decision.get("candidate_indices", [])) == 1:
            candidate = data["companies"][decision["candidate_indices"][0]]
            record = RawCompany(**{k: v for k, v in candidate.items() if k in fields})
            project.initiator_company_id = company_ids.get(match_key(record).company_key)
        session.flush()
        replace_needs(session, project.id, row["recommendations"])
    for cell in data.get("territories", []):
        code = next(
            (
                p.get("region_code")
                for p in [*sources, *data["projects"]]
                if p.get("municipality") == cell["municipality"]
            ),
            None,
        )
        rid = regions.get((code, cell["municipality"]))
        if cell["aggregation_level"] == "region":
            rid = regions.get((cell["municipality"].removeprefix("region:"), None))
        if rid is not None:
            _snapshot(session, "region", rid, cell, industry=cell["industry"])
    session.flush()
    return {
        "created_companies": created,
        "created_projects": project_count,
        "processed_projects": len(data["projects"]),
    }


def saved_company_score(session, company_id):
    snapshot = session.scalar(
        select(ScoringSnapshot)
        .where(
            ScoringSnapshot.subject_type == "company",
            ScoringSnapshot.subject_id == company_id,
        )
        .order_by(ScoringSnapshot.calculated_at.desc(), ScoringSnapshot.id.desc())
        .limit(1)
    )
    if snapshot is None:
        return {"score": None, "data_quality": "not_calculated", "factors": []}
    return {**snapshot.factors_json[0], "calculated_at": snapshot.calculated_at}
