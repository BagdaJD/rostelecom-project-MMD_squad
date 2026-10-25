from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, update

from app.core import audit
from app.core.deps import CurrentUser, DbSession
from app.models import SavedFilter, User
from app.schemas.preferences import (
    SavedFilterIn,
    SavedFilterOut,
    SavedFilterPatch,
    validate_filters,
)

router = APIRouter(prefix="/saved-filters", tags=["saved-filters"])


def owned(session, user, filter_id):
    row = session.scalar(
        select(SavedFilter).where(SavedFilter.id == filter_id, SavedFilter.user_id == user.id)
    )
    if row is None:
        raise HTTPException(404, "Фильтр не найден")
    return row


def clear_default(session, user_id, module):
    session.execute(
        update(SavedFilter)
        .where(SavedFilter.user_id == user_id, SavedFilter.module == module)
        .values(is_default=False)
    )
    session.flush()


@router.get("", response_model=list[SavedFilterOut])
def list_filters(
    session: DbSession,
    user: CurrentUser,
    module: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    statement = select(SavedFilter).where(SavedFilter.user_id == user.id)
    if module is not None:
        statement = statement.where(SavedFilter.module == module)
    return session.scalars(statement.order_by(SavedFilter.id).limit(limit).offset(offset)).all()


@router.post("", response_model=SavedFilterOut, status_code=201)
def create_filter(payload: SavedFilterIn, session: DbSession, user: CurrentUser):
    session.scalar(select(User.id).where(User.id == user.id).with_for_update())
    if payload.is_default:
        clear_default(session, user.id, payload.module)
    row = SavedFilter(
        user_id=user.id,
        module=payload.module,
        name=payload.name,
        filters_json=payload.filters,
        is_default=payload.is_default,
    )
    session.add(row)
    session.flush()
    audit.record(session, user.id, "saved_filter.create", "saved_filter", row.id)
    session.commit()
    return row


@router.patch("/{filter_id}", response_model=SavedFilterOut)
def patch_filter(filter_id: int, payload: SavedFilterPatch, session: DbSession, user: CurrentUser):
    session.scalar(select(User.id).where(User.id == user.id).with_for_update())
    row = owned(session, user, filter_id)
    values = payload.model_dump(exclude_unset=True)
    if any(value is None for value in values.values()):
        raise HTTPException(422, "Поля изменения не могут быть null")
    if "filters" in values:
        try:
            row.filters_json = validate_filters(row.module, values.pop("filters"))
        except ValueError as error:
            raise HTTPException(422, "Некорректные фильтры") from error
    if values.get("is_default"):
        clear_default(session, user.id, row.module)
    for name, value in values.items():
        setattr(row, name, value)
    audit.record(session, user.id, "saved_filter.update", "saved_filter", row.id)
    session.commit()
    return row


@router.delete("/{filter_id}")
def delete_filter(filter_id: int, session: DbSession, user: CurrentUser):
    row = owned(session, user, filter_id)
    session.delete(row)
    audit.record(session, user.id, "saved_filter.delete", "saved_filter", filter_id)
    session.commit()
    return {"status": "deleted"}
