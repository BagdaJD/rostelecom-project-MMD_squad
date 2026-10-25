"""Durable export requests with leases; Redis is only the delivery mechanism."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import or_, select, update

from app.core.config import get_settings
from app.models import AuditLog, BackgroundTask
from app.schemas import ExportCsvRequest
from modules.exports import service

MAX_ATTEMPTS = 3
LEASE_SECONDS = 660
CHUNK_SIZE = 500


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def create(session, user_id, payload):
    task = BackgroundTask(
        id=str(uuid4()),
        user_id=user_id,
        kind="export.csv",
        params=payload.model_dump(),
        status="pending",
        attempts=0,
    )
    session.add(task)
    session.add(
        AuditLog(
            user_id=user_id,
            action="export.request",
            object_type="background_task",
            object_id=task.id,
        )
    )
    session.flush()
    return task


def public(task):
    prefix = get_settings().api_prefix
    return {
        "id": task.id,
        "kind": task.kind,
        "status": task.status,
        "attempts": task.attempts,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "error": task.error,
        "status_url": f"{prefix}/tasks/{task.id}",
        "download_url": f"{prefix}/exports/{task.id}/download" if task.status == "done" else None,
    }


def generate(task_id, *, session_factory=None, now=None):
    from app.db.session import SessionLocal

    factory = session_factory or SessionLocal
    now = now or datetime.now(UTC)
    token = str(uuid4())
    with factory() as session:
        task = session.get(BackgroundTask, task_id, with_for_update=True)
        if task is None or task.status in ("done", "failed"):
            return False
        if task.status == "running" and task.lease_until and utc(task.lease_until) > now:
            return False
        if task.attempts >= MAX_ATTEMPTS:
            task.status, task.finished_at = "failed", now
            task.error = "Не удалось сформировать экспорт после трёх попыток"
            session.commit()
            return False
        task.status, task.attempts = "running", task.attempts + 1
        task.lease_token, task.lease_until = token, now + timedelta(seconds=LEASE_SECONDS)
        task.started_at, task.error = now, None
        params, user_id = task.params, task.user_id
        session.commit()

    root = Path(get_settings().export_dir).resolve()
    target = root / f"export-{task_id}-{token}.csv"
    partial = target.with_suffix(".part")
    try:
        payload = ExportCsvRequest.model_validate(params)
        root.mkdir(parents=True, exist_ok=True)
        rows_fn = (
            service.companies_rows if payload.module == "companies" else service.investment_rows
        )

        with factory() as session:
            if session.get_bind().dialect.name == "postgresql":
                session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            with partial.open("w", encoding="utf-8-sig", newline="") as output:
                offset = 0
                while True:
                    rows = rows_fn(session, payload.filters, limit=CHUNK_SIZE, offset=offset)
                    service.write_csv(
                        output, rows, payload.module, payload.mode, header=offset == 0
                    )
                    if len(rows) < CHUNK_SIZE:
                        break
                    offset += len(rows)
        partial.replace(target)
        with factory() as session:
            result = session.execute(
                update(BackgroundTask)
                .where(
                    BackgroundTask.id == task_id,
                    BackgroundTask.status == "running",
                    BackgroundTask.lease_token == token,
                )
                .values(
                    status="done",
                    file_ref=str(target),
                    finished_at=datetime.now(UTC),
                    lease_until=None,
                    lease_token=None,
                    error=None,
                )
            )
            if result.rowcount != 1:
                target.unlink(missing_ok=True)
                return False
            session.add(
                AuditLog(
                    user_id=user_id,
                    action="export.ready",
                    object_type="background_task",
                    object_id=task_id,
                )
            )
            session.commit()
        return True
    except Exception:
        partial.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        with factory() as session:
            task = session.get(BackgroundTask, task_id, with_for_update=True)
            if task and task.lease_token == token:
                task.status = "pending" if task.attempts < MAX_ATTEMPTS else "failed"
                task.error = (
                    "Ошибка формирования экспорта; задача будет повторена"
                    if task.status == "pending"
                    else "Не удалось сформировать экспорт"
                )
                task.lease_token = task.lease_until = None
                task.finished_at = datetime.now(UTC) if task.status == "failed" else None
                session.commit()
        raise


def dispatch(queue=None, *, session_factory=None):
    from redis import Redis
    from rq import Queue, Retry

    from app.db.session import SessionLocal

    factory = session_factory or SessionLocal
    queue = (
        queue
        if queue is not None
        else Queue(
            "default", connection=Redis.from_url(get_settings().redis_url), default_timeout=600
        )
    )
    now = datetime.now(UTC)
    with factory() as session:
        rows = list(
            session.scalars(
                select(BackgroundTask)
                .where(
                    or_(
                        BackgroundTask.status == "pending",
                        (BackgroundTask.status == "running") & (BackgroundTask.lease_until <= now),
                    )
                )
                .order_by(BackgroundTask.created_at)
                .limit(500)
            )
        )
        count = 0
        for task in rows:
            if task.attempts >= MAX_ATTEMPTS:
                task.status, task.finished_at = "failed", now
                task.error = "Не удалось сформировать экспорт после трёх попыток"
                continue
            job_id = f"export-{task.id}-{task.attempts}"
            existing = queue.fetch_job(job_id)
            if existing and existing.get_status() in ("queued", "started", "scheduled", "deferred"):
                continue
            queue.enqueue(
                generate,
                task.id,
                job_id=job_id,
                retry=Retry(max=2, interval=[10, 30]),
                job_timeout=600,
                result_ttl=3600,
            )
            count += 1
        session.commit()
    return count
