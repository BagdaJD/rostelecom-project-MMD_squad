"""API калькулятора сделок (модуль 3): /calculator/*.

Отдельный набор маршрутов: прежний POST /deals/estimate не меняется. Расчёт, утверждение
цены, КП в DOCX и выгрузки CSV живут здесь же, на таблицах calc_* (modules/deal_calculator).
"""

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response, status

from app.core import audit
from app.core.access import calculator_estimate
from app.core.deps import CurrentUser, DbSession, ManagerOrAdmin
from app.models import Company, InvestmentProject
from modules.deal_calculator import export, proposal
from modules.deal_calculator import service as calculator
from modules.deal_calculator.models import CalcRegion
from modules.deal_calculator.schemas import ApproveIn, EstimateRequest, EstimateResponse

router = APIRouter(prefix="/calculator", tags=["calculator"])

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _attachment(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/catalog")
def catalog(session: DbSession, user: CurrentUser) -> dict:
    """Каталог позиций по системам, уровни, регионы с коэффициентами, параметры расчёта."""
    return calculator.catalog_payload(session)


@router.post("/estimate", response_model=EstimateResponse)
def estimate(payload: EstimateRequest, session: DbSession, user: CurrentUser) -> EstimateResponse:
    """Себестоимость, вилка, аналоги, кривая маржи. Итог утверждает сотрудник (ТЗ 8.3)."""
    if payload.company_id is not None and session.get(Company, payload.company_id) is None:
        raise HTTPException(404, "Компания не найдена")
    if payload.investment_project_id is not None:
        project = session.get(InvestmentProject, payload.investment_project_id)
        if project is None:
            raise HTTPException(404, "Инвестпроект не найден")
        if payload.company_id is not None and payload.company_id != project.initiator_company_id:
            raise HTTPException(422, "Компания не соответствует инициатору инвестпроекта")
    if payload.region_id is not None and session.get(CalcRegion, payload.region_id) is None:
        raise HTTPException(422, "Регион калькулятора не найден")
    return calculator.estimate(session, payload, author_id=user.id)


@router.post("/estimates/{estimate_id}/approve")
def approve(estimate_id: int, payload: ApproveIn, session: DbSession, user: ManagerOrAdmin) -> dict:
    calculator_estimate(session, estimate_id, user)
    try:
        row = calculator.approve(session, estimate_id, payload.price, user.id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {
        "estimate_id": row.id,
        "approved_price": row.approved_price,
        "approved_at": row.approved_at,
    }


@router.get("/estimates/{estimate_id}/proposal")
def proposal_docx(
    estimate_id: int,
    session: DbSession,
    user: CurrentUser,
    variant: Literal["client", "internal"] = "client",
) -> Response:
    """КП в Word: client — для заказчика, internal — с приложением «Обоснование цены»."""
    calculator_estimate(session, estimate_id, user)
    if variant == "internal" and user.role not in ("admin", "analyst"):
        raise HTTPException(403, "Внутреннее обоснование доступно аналитику и администратору")
    try:
        content = proposal.build_proposal(session, estimate_id, variant)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    suffix = "-internal" if variant == "internal" else ""
    audit.record(
        session,
        user.id,
        "calculator.proposal",
        "calc_estimate",
        estimate_id,
        after={"variant": variant},
    )
    session.commit()
    return _attachment(content, DOCX, f"KP-{estimate_id}{suffix}.docx")


@router.get("/estimates/{estimate_id}/csv")
def csv_export(
    estimate_id: int,
    session: DbSession,
    user: CurrentUser,
    kind: Literal["deals", "comparables", "crm"] = "deals",
) -> Response:
    """CSV: deals и comparables — для Excel («;»), crm — для импорта в CRM (RFC 4180)."""
    calculator_estimate(session, estimate_id, user)
    content = export.export_csv(session, kind, estimate_id)
    audit.record(
        session, user.id, "calculator.csv", "calc_estimate", estimate_id, after={"kind": kind}
    )
    session.commit()
    return _attachment(content, "text/csv; charset=utf-8", f"calculator-{kind}-{estimate_id}.csv")


@router.get("/draft/{project_id}")
def draft(project_id: int, session: DbSession, user: CurrentUser) -> dict:
    """Черновик параметров из инвестпроекта навигатора: /calculator?project=ID на фронте."""
    result = calculator.draft_from_project(session, project_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
    return result
