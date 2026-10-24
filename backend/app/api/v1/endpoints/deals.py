from fastapi import APIRouter

from app.core.deps import CurrentUser, DbSession
from app.schemas import DealEstimateRequest, DealEstimateResponse
from modules.deals import service as deals

router = APIRouter(prefix="/deals", tags=["deals"])


@router.post("/estimate", response_model=DealEstimateResponse)
def estimate(payload: DealEstimateRequest, session: DbSession, user: CurrentUser) -> DealEstimateResponse:
    """Диапазон по аналогам. Итог всегда утверждает сотрудник (ТЗ 8.3)."""
    return deals.estimate(session, payload, author_id=user.id)
