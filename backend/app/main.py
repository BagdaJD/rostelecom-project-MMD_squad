"""Точка входа FastAPI.

Важное архитектурное ограничение (ТЗ 5): здесь не обращаются к внешним источникам —
загрузка данных выполняется воркером, HTTP-слой читает нормализованные записи.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app.api.v1.api import api_router
from app.core.config import get_settings
from app.core.ratelimit import RateLimitUnavailable
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
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.middleware("http")
async def auth_no_store(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(f"{settings.api_prefix}/auth/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


@app.exception_handler(ValueError)
def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(RateLimitUnavailable)
def rate_limit_unavailable(request: Request, exc: RateLimitUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/health", tags=["service"])
def health() -> dict:
    """Liveness без обращения к БД: проверка процесса."""
    return {"status": "ok", "env": settings.app_env}


@app.get(f"{settings.api_prefix}/ready", tags=["service"])
def ready() -> dict:
    """Readiness проверяет схему и оба обязательных сервиса, без выдачи DSN/секретов."""
    from redis import Redis

    checks = {}
    try:
        with SessionLocal() as session:
            companies = session.scalar(select(Company.id).limit(1))
            version = session.scalar(text("SELECT version_num FROM alembic_version"))
        checks["database"] = "ok"
        checks["schema"] = "ok" if version == "20261025_0005" else "migration_required"
        checks["seeded"] = companies is not None
    except Exception:
        checks["database"] = "unavailable"
    try:
        with Redis.from_url(
            settings.redis_url, socket_connect_timeout=1, socket_timeout=1
        ) as redis:
            redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"
    is_ready = all(checks.get(key) == "ok" for key in ("database", "schema", "redis"))
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={"status": "ready" if is_ready else "not_ready", **checks},
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
