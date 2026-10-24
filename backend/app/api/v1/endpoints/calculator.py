"""API калькулятора сделок (модуль 3): /calculator/*.

Отдельный набор маршрутов: прежний POST /deals/estimate не меняется. Расчёт, утверждение
цены, КП в DOCX и выгрузки CSV живут здесь же, на таблицах calc_* (modules/deal_calculator).
"""

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response, status

from app.core.deps import CurrentUser, DbSession
from modules.deal_calculator import export, proposal
from modules.deal_calculator import service as calculator
from modules.deal_calculator.schemas import ApproveIn, EstimateRequest, EstimateResponse

router = APIRouter(prefix="/calculator", tags=["calculator"])

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _attachment(content: bytes, media_type: str, filename: str) -> Response:
    return Response(content, media_type=media_type, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@router.get("/catalog")
def catalog(session: DbSession, user: CurrentUser) -> dict:
    """Каталог позиций по системам, уровни, регионы с коэффициентами, параметры расчёта."""
    return calculator.catalog_payload(session)


@router.post("/estimate", response_model=EstimateResponse)
def estimate(payload: EstimateRequest, session: DbSession, user: CurrentUser) -> EstimateResponse:
    """Себестоимость, вилка, аналоги, кривая маржи. Итог утверждает сотрудник (ТЗ 8.3)."""
    return calculator.estimate(session, payload, author_id=user.id)


@router.post("/estimates/{estimate_id}/approve")
def approve(estimate_id: int, payload: ApproveIn, session: DbSession, user: CurrentUser) -> dict:
    try:
        row = calculator.approve(session, estimate_id, payload.price, user.id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {"estimate_id": row.id, "approved_price": row.approved_price,
            "approved_at": row.approved_at}


@router.get("/estimates/{estimate_id}/proposal")
def proposal_docx(estimate_id: int, session: DbSession, user: CurrentUser,
                  variant: Literal["client", "internal"] = "client") -> Response:
    """КП в Word: client — для заказчика, internal — с приложением «Обоснование цены»."""
    try:
        content = proposal.build_proposal(session, estimate_id, variant)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    suffix = "-internal" if variant == "internal" else ""
    return _attachment(content, DOCX, f"KP-{estimate_id}{suffix}.docx")


@router.get("/estimates/{estimate_id}/csv")
def csv_export(estimate_id: int, session: DbSession, user: CurrentUser,
               kind: Literal["deals", "comparables", "crm"] = "deals") -> Response:
    """CSV: deals и comparables — для Excel («;»), crm — для импорта в CRM (RFC 4180)."""
    content = export.export_csv(session, kind, estimate_id)
    return _attachment(content, "text/csv; charset=utf-8", f"calculator-{kind}-{estimate_id}.csv")


@router.get("/draft/{project_id}")
def draft(project_id: int, session: DbSession, user: CurrentUser) -> dict:
    """Черновик параметров из инвестпроекта навигатора: /calculator?project=ID на фронте."""
    result = calculator.draft_from_project(session, project_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
    return result
