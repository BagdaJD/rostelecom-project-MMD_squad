"""Worker: очередь задач и плановые загрузки (RQ + APScheduler).

Выбор RQ вместо Celery осознанный: для 2–3 источников достаточно очередей с повторами,
а конфигурации на порядок меньше. Celery подключаем, когда появятся приоритеты,
сложные ретраи или несколько очередей (ТЗ 4).
"""

from __future__ import annotations

import logging

from app.db.session import SessionLocal
from app.workers import jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("worker")


def main() -> None:
    """Один процесс: планировщик в фоне, потребитель очереди в основном потоке."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from redis import Redis
    from rq import Worker

    from app.core.config import get_settings

    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)

    scheduler = BackgroundScheduler(timezone="Europe/Moscow")
    scheduler.add_job(jobs.run_ingestion, "interval", minutes=30, kwargs={"settings": settings},
                      id="ingest", max_instances=1, coalesce=True)
    scheduler.add_job(jobs.refresh_scoring, "interval", minutes=30, id="scoring",
                      max_instances=1, coalesce=True)
    scheduler.add_job(jobs.dispatch_notifications, "interval", minutes=15, id="notifications",
                      max_instances=1, coalesce=True)
    scheduler.add_job(jobs.rebuild_matviews, "cron", hour=3, id="matviews")
    scheduler.start()
    log.info("worker started: очередь + планировщик")
    try:
        Worker([redis], connection=redis, job_timeout="10m").work(burst=False)
    except KeyboardInterrupt:
        log.info("worker stopped")
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
