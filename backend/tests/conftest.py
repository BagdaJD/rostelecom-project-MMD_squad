"""Общая настройка тестов: окружение должно быть задано до импорта приложения."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-0123456789")
os.environ.setdefault("TOTP_ENCRYPTION_KEY", "test-totp-key-not-for-production-0123456789")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://rtk:rtk@localhost:5432/rtk_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
