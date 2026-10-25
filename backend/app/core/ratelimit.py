"""Shared Redis limits; an in-memory fallback is limited to dev/test."""

from __future__ import annotations

import time
import uuid

import redis

from app.core.config import get_settings

_memory: dict[str, list[float]] = {}


class RateLimitUnavailable(RuntimeError):
    pass


def _redis():
    return redis.Redis.from_url(
        get_settings().redis_url, socket_connect_timeout=0.3, socket_timeout=0.5
    )


def _unavailable(error: Exception) -> None:
    if get_settings().app_env not in ("dev", "test"):
        raise RateLimitUnavailable("Сервис ограничения попыток временно недоступен") from error


def client_key(scope: str, identity: str, ip: str | None) -> str:
    return f"rl:{scope}:{identity or 'anon'}:{ip or 'no-ip'}"


def is_limited(key: str, limit: int | None = None, window: int | None = None) -> bool:
    limit = limit or get_settings().rate_limit_login
    window = window or get_settings().rate_limit_window_sec
    now = time.time()
    try:
        with _redis() as client:
            pipeline = client.pipeline()
            pipeline.zremrangebyscore(key, 0, now - window)
            pipeline.zadd(key, {uuid.uuid4().hex: now})
            pipeline.zcard(key)
            pipeline.expire(key, window)
            _, _, count, _ = pipeline.execute()
            return int(count) > limit
    except redis.RedisError as error:
        _unavailable(error)
    hits = [t for t in _memory.get(key, []) if t > now - window]
    hits.append(now)
    _memory[key] = hits
    return len(hits) > limit


def reset(key: str) -> None:
    try:
        with _redis() as client:
            client.delete(key)
    except redis.RedisError as error:
        _unavailable(error)
    _memory.pop(key, None)
