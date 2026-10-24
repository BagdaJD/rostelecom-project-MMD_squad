from fastapi import APIRouter

from app.api.v1.endpoints import auth, deals, exports, investments, notifications, radar

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(radar.router)
api_router.include_router(investments.router)
api_router.include_router(investments.subscriptions_router)
api_router.include_router(deals.router)
api_router.include_router(exports.router)
api_router.include_router(notifications.router)
