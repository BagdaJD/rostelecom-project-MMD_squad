from fastapi import APIRouter, Response

from app.core import audit
from app.core.access import legacy_estimate
from app.core.deps import CurrentUser, DbSession
from app.schemas import DealEstimateRequest, DealEstimateResponse
from modules.deals import service as deals
from modules.exports import service as exports

router = APIRouter(prefix="/deals", tags=["deals"])


@router.post("/estimate", response_model=DealEstimateResponse)
def estimate(
    payload: DealEstimateRequest, session: DbSession, user: CurrentUser
) -> DealEstimateResponse:
    """Диапазон по аналогам. Итог всегда утверждает сотрудник (ТЗ 8.3)."""
    result = deals.estimate(session, payload, author_id=user.id)
    audit.record(
        session,
        user.id,
        "deals.estimate",
        "deal_estimate",
        result.estimate_id,
        after={"request": payload.model_dump(mode="json"), "model_version": result.model_version},
    )
    session.commit()
    return result


@router.get("/estimates/{estimate_id}/csv")
def estimate_csv(estimate_id: int, session: DbSession, user: CurrentUser) -> Response:
    """CSV расчёта из POST /deals/estimate: вилка, поправки, аналоги.

    Номер — из deal_estimate; /calculator/estimates/{id}/csv работает с другой таблицей.
    """
    legacy_estimate(session, estimate_id, user)  # автор или admin, иначе 404
    content = exports.to_csv(exports.deal_estimate_rows(session, estimate_id), "deal_estimate")
    audit.record(session, user.id, "deals.csv", "deal_estimate", estimate_id)
    session.commit()
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="deal-estimate-{estimate_id}.csv"'},
    )
