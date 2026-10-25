"""Worker: очередь задач и плановые загрузки (RQ + APScheduler).

Выбор RQ вместо Celery осознанный: для 2–3 источников достаточно очередей с повторами,
а конфигурации на порядок меньше. Celery подключаем, когда появятся приоритеты,
сложные ретраи или несколько очередей (ТЗ 4).
"""

from __future__ import annotations

import logging
import sys

from app.workers import jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("worker")


def enqueue_periodic(queue, function, name):
    """Coalesce timer ticks across processes while a prior job is still active."""
    from rq import Retry

    key = f"telecom:periodic:{name}"
    with queue.connection.lock(f"{key}:lock", timeout=10, blocking_timeout=2):
        job_id = queue.connection.get(key)
        existing = (
            queue.fetch_job(job_id.decode() if isinstance(job_id, bytes) else job_id)
            if job_id
            else None
        )
        if existing and existing.get_status() in ("queued", "started", "scheduled", "deferred"):
            return None
        job = queue.enqueue(
            function, retry=Retry(max=2, interval=[10, 30]), job_timeout=600, result_ttl=3600
        )
        queue.connection.set(key, job.id, ex=86400)
        return job.id


def build_scheduler(queue, settings):
    """Планировщик ставит задачи в RQ; работа с БД идёт только в consumer."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BackgroundScheduler(timezone="Europe/Moscow")
    schedules = (
        (
            "ingest",
            jobs.run_ingestion,
            CronTrigger.from_crontab(settings.ingest_cron, timezone="Europe/Moscow"),
            {},
        ),
        ("scoring", jobs.refresh_scoring, "interval", {"minutes": 30}),
        ("notifications", jobs.dispatch_notifications, "interval", {"minutes": 1}),
        ("matviews", jobs.rebuild_matviews, "interval", {"minutes": 5}),
        ("models", jobs.refresh_models, "interval", {"minutes": 30}),
        ("exports", jobs.dispatch_export_tasks, "interval", {"minutes": 1}),
    )
    for name, function, trigger, trigger_options in schedules:
        scheduler.add_job(
            enqueue_periodic,
            trigger,
            args=[queue, function, name],
            id=name,
            max_instances=1,
            coalesce=True,
            **trigger_options,
        )
    return scheduler


def main() -> None:
    """Планировщик в фоне, RQ consumer в основном потоке (Linux/Docker)."""
    from redis import Redis
    from rq import Queue, SimpleWorker, Worker
    from rq.timeouts import TimerDeathPenalty

    from app.core.config import get_settings

    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)

    queue = Queue("default", connection=redis, default_timeout=600)
    scheduler = build_scheduler(queue, settings)
    scheduler.start()
    log.info("worker started: очередь + планировщик")
    try:
        if sys.platform == "win32":
            worker = SimpleWorker([queue], connection=redis)
            worker.death_penalty_class = TimerDeathPenalty
        else:
            worker = Worker([queue], connection=redis)
        worker.work(burst=False, with_scheduler=True)
    except KeyboardInterrupt:
        log.info("worker stopped")
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
