"""Конфигурация приложения. Значения только из окружения — без секретов в коде."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPOSITORY_ROOT / ".env", BACKEND_ROOT / ".env"), extra="ignore"
    )

    app_env: str = "dev"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://rtk:rtk@localhost:5432/rtk"
    database_connect_timeout_sec: int = Field(default=3, ge=1, le=30)
    redis_url: str = "redis://localhost:6379/0"

    secret_key: str = Field(min_length=16)
    totp_encryption_key: str = Field(min_length=16)
    access_token_ttl_min: int = 15
    refresh_token_ttl_days: int = 7
    partial_auth_ttl_min: int = 5
    auth_cookie_secure: bool | None = None

    cors_origins: list[str] = ["http://localhost:5173"]

    rate_limit_login: int = 5
    rate_limit_window_sec: int = 900

    ingest_enabled: bool = False
    ingest_cron: str = "*/30 * * * *"
    demo_bundle_path: Path = REPOSITORY_ROOT / "data" / "seed" / "demo_bundle.json"
    case_workbook_path: Path = REPOSITORY_ROOT / "data" / "case" / "case_data_2026.xlsx"
    data_mode: Literal["case", "demo"] = "case"
    export_dir: str = "exports"

    scoring_mode: str = "heuristic"
    model_version: str = "radar-scoring-0.2"

    @property
    def secure_cookies(self) -> bool:
        return (
            self.auth_cookie_secure
            if self.auth_cookie_secure is not None
            else (self.app_env not in ("dev", "test"))
        )

    @model_validator(mode="after")
    def secure_production_cookies(self):
        if self.app_env not in ("dev", "test") and not self.secure_cookies:
            raise ValueError("AUTH_COOKIE_SECURE must be true outside dev/test")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
