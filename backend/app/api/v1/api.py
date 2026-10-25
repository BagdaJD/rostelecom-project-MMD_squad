from fastapi import APIRouter

from app.api.v1.endpoints import (
    audit,
    auth,
    deals,
    exports,
    investments,
    notifications,
    preferences,
    radar,
    reference,
)
from app.api.v1.endpoints.calculator import router as calculator_router

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(radar.router)
api_router.include_router(investments.router)
api_router.include_router(investments.subscriptions_router)
api_router.include_router(deals.router)
api_router.include_router(exports.router)
api_router.include_router(exports.tasks_router)
api_router.include_router(notifications.router)
api_router.include_router(calculator_router)
api_router.include_router(reference.router)
api_router.include_router(audit.router)
api_router.include_router(preferences.router)
