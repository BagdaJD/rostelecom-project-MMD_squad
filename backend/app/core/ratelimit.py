"""Ограничение частоты попыток входа и подтверждения 2FA (ТЗ 13).

Без этого 2FA обходится перебором шестизначного кода. Счётчики в Redis,
fallback в памяти — только для локальной разработки без Redis.
"""

from __future__ import annotations

import time

from app.core.config import get_settings

_memory: dict[str, list[float]] = {}


def _redis():
    try:
        import redis

        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=0.3)
        client.ping()
        return client
    except Exception:  # noqa: BLE001 — отсутствие Redis не должно ломать вход в dev
        return None


def client_key(scope: str, identity: str, ip: str | None) -> str:
    return f"rl:{scope}:{identity or 'anon'}:{ip or 'no-ip'}"


def is_limited(key: str, limit: int | None = None, window: int | None = None) -> bool:
    limit = limit or get_settings().rate_limit_login
    window = window or get_settings().rate_limit_window_sec
    now = time.time()

    client = _redis()
    if client is not None:
        pipeline = client.pipeline()
        pipeline.zremrangebyscore(key, 0, now - window)
        pipeline.zadd(key, {str(now): now})
        pipeline.zcard(key)
        pipeline.expire(key, window)
        _, _, count, _ = pipeline.execute()
        return int(count) > limit

    hits = [t for t in _memory.get(key, []) if t > now - window]
    hits.append(now)
    _memory[key] = hits
    return len(hits) > limit


def reset(key: str) -> None:
    client = _redis()
    if client is not None:
        client.delete(key)
    _memory.pop(key, None)
