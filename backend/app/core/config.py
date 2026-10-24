"""Конфигурация приложения. Значения только из окружения — без секретов в коде."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://rtk:rtk@localhost:5432/rtk"
    redis_url: str = "redis://localhost:6379/0"

    secret_key: str = Field(min_length=16)
    totp_encryption_key: str = Field(min_length=16)
    access_token_ttl_min: int = 15
    refresh_token_ttl_days: int = 7
    partial_auth_ttl_min: int = 5

    cors_origins: list[str] = ["http://localhost:5173"]

    rate_limit_login: int = 5
    rate_limit_window_sec: int = 900

    ingest_enabled: bool = False
    export_dir: str = "exports"

    # Модели по умолчанию работают на правилах; режим проявляется в ответах API (раздел 8 ТЗ).
    scoring_mode: str = "heuristic"
    model_version: str = "radar-scoring-0.1"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
