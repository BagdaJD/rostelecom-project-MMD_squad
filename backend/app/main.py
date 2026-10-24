"""Точка входа FastAPI.

Важное архитектурное ограничение (ТЗ 5): здесь не обращаются к внешним источникам —
загрузка данных выполняется воркером, HTTP-слой читает нормализованные записи.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.v1.api import api_router
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Company
from modules.radar.service import derive_client_status

settings = get_settings()

app = FastAPI(
    title="Экосистема коммерческого блока",
    version="0.1.0",
    description="Прототип для кейса ПАО «Ростелеком». Данные демонстрационные.",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.exception_handler(ValueError)
def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/health", tags=["service"])
def health() -> dict:
    """Liveness без обращения к БД: проверка процесса."""
    return {"status": "ok", "env": settings.app_env}


@app.get(f"{settings.api_prefix}/ready", tags=["service"])
def ready() -> dict:
    """Readiness с проверкой БД."""
    try:
        with SessionLocal() as session:
            companies = session.scalar(select(Company.id).limit(1))
        return {"status": "ready", "database": "ok", "seeded": companies is not None}
    except Exception as exc:  # noqa: BLE001 — готовность не должна ронять сервис
        return JSONResponse(
            status_code=503, content={"status": "not_ready", "database": str(exc)[:200]}
        )


@app.get(f"{settings.api_prefix}/client-status-rules", tags=["service"])
def client_status_rules() -> dict:
    """Легенда статусов клиентов: правило открыто, а не «чёрный ящик» (ТЗ 7)."""
    return {
        "active": derive_client_status(True, False),
        "prospect": derive_client_status(False, True),
        "unknown": derive_client_status(False, False),
        "rule": "присутствие услуги → действующий; сигнал спроса без присутствия → потенциальный",
    }
