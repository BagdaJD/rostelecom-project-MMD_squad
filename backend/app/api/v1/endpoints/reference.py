from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models import (
    Company,
    DictionaryItem,
    Industry,
    InvestmentProject,
    PositionPrice,
    Region,
    SourceRecord,
)
from app.schemas.companies import DictionaryOut, IndustryOut, PositionOut, RegionOut
from modules.radar.companies import provenance

router = APIRouter(tags=["reference"])


@router.get("/regions", response_model=list[RegionOut])
def regions(session: DbSession, user: CurrentUser):
    return session.scalars(select(Region).order_by(Region.name, Region.id)).all()


@router.get("/regions/{region_id}/municipalities")
def municipalities(region_id: int, session: DbSession, user: CurrentUser):
    if session.get(Region, region_id) is None:
        raise HTTPException(404, "Регион не найден")
    names = set(session.scalars(select(Company.municipality).where(Company.region_id == region_id)))
    names.update(
        session.scalars(
            select(InvestmentProject.municipality).where(InvestmentProject.region_id == region_id)
        )
    )
    return [{"name": name} for name in sorted(value for value in names if value)]


@router.get("/industries", response_model=list[IndustryOut])
def industries(session: DbSession, user: CurrentUser):
    return session.scalars(select(Industry).order_by(Industry.name, Industry.id)).all()


@router.get("/dictionaries/{code}", response_model=list[DictionaryOut])
def dictionary(code: str, session: DbSession, user: CurrentUser):
    rows = session.scalars(
        select(DictionaryItem)
        .where(DictionaryItem.dict_code == code)
        .order_by(DictionaryItem.order_no, DictionaryItem.code)
    ).all()
    if not rows:
        raise HTTPException(404, "Справочник не найден")
    return rows


@router.get("/positions/prices", response_model=list[PositionOut])
def positions(
    session: DbSession,
    user: CurrentUser,
    category: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    statement = select(PositionPrice)
    if category:
        statement = statement.where(PositionPrice.category == category)
    return session.scalars(
        statement.order_by(PositionPrice.name, PositionPrice.id).limit(limit).offset(offset)
    ).all()


@router.get("/sources/{source_id}")
def source(source_id: int, session: DbSession, user: CurrentUser):
    row = session.get(SourceRecord, source_id)
    if row is None:
        raise HTTPException(404, "Источник не найден")
    return {
        **provenance(row).model_dump(mode="json"),
        "raw_payload": row.raw_payload,
        "payload_hash": row.payload_hash,
        "processing_status": row.processing_status,
    }
