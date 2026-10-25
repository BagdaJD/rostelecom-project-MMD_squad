"""Checks that can run without Docker; PostgreSQL migrations have a separate suite."""

import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock

from alembic.config import Config
from rq import Queue, Worker

from alembic import command
from app.core.config import get_settings
from app.db.base import Base
from app.workers import jobs
from app.workers.main import build_scheduler
from ingestion.normalize import RawCompany, match_key
from ingestion.sources import DemoSource

BACKEND = Path(__file__).resolve().parents[1]


def test_offline_migrations_create_all_tables_and_spatial_indexes_once():
    output = io.StringIO()
    config = Config(str(BACKEND / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    for table in Base.metadata.sorted_tables:
        assert re.search(rf'CREATE TABLE "?{table.name}"?\s*\(', sql), table.name
    assert "CREATE EXTENSION IF NOT EXISTS postgis" in sql
    assert "ALTER TABLE notification ADD COLUMN created_at" in sql
    assert "DEFAULT now() NOT NULL" in sql
    for name in (
        "idx_company_coordinates",
        "idx_region_geometry",
        "idx_investment_project_coordinates",
    ):
        assert sql.count(f"CREATE INDEX {name} ") == 1, name


def test_offline_downgrade_keeps_shared_postgis_extension():
    output = io.StringIO()
    config = Config(str(BACKEND / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    command.downgrade(config, "head:base", sql=True)
    sql = output.getvalue()
    assert "DROP TABLE calc_estimate" in sql
    assert "DROP TABLE company" in sql
    assert "DROP EXTENSION" not in sql


def test_demo_source_uses_repository_data_from_any_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert len(DemoSource().fetch()["companies"]) == 48


def test_company_payload_is_json_safe_and_fallback_key_ignores_retrieval_time():
    first = RawCompany(source="demo", external_id="one", name="Без идентификаторов")
    second = RawCompany(
        source="demo", external_id="one", name=first.name, fetched_at="2026-10-25T09:00:00+00:00"
    )
    json.dumps(first.as_dict())
    assert isinstance(second.fetched_at, datetime)
    assert second.fetched_at.tzinfo == UTC
    assert match_key(first).company_key == match_key(second).company_key


def test_scheduler_enqueues_tasks_and_honours_ingestion_cron():
    settings = get_settings().model_copy(update={"ingest_cron": "5 * * * *"})
    queue = Mock(spec=Queue)
    queue.connection = MagicMock()
    queue.connection.get.return_value = None
    scheduler = build_scheduler(queue, settings)
    ingest = scheduler.get_job("ingest")
    next_run = ingest.trigger.get_next_fire_time(None, datetime(2026, 10, 25, 9, 0, tzinfo=UTC))
    assert next_run.minute == 5 and next_run.second == 0
    ingest.func(*ingest.args, **ingest.kwargs)
    assert queue.enqueue.call_count == 1
    assert queue.enqueue.call_args.args == (jobs.run_ingestion,)
    retry = queue.enqueue.call_args.kwargs["retry"]
    assert retry.max == 2 and retry.intervals == [10, 30]
    queue.connection.get.return_value = b"previous-job"
    queue.fetch_job.return_value.get_status.return_value = "queued"
    ingest.func(*ingest.args, **ingest.kwargs)
    assert queue.enqueue.call_count == 1
    assert {job.id for job in scheduler.get_jobs()} == {
        "ingest",
        "scoring",
        "notifications",
        "matviews",
        "models",
        "exports",
    }


def test_worker_accepts_named_queue_without_connecting():
    from redis import Redis

    connection = Redis()
    queue = Queue("default", connection=connection, default_timeout=600)
    worker = Worker([queue], connection=connection, prepare_for_work=False)
    assert worker.queue_names() == ["default"]


def test_disabled_ingestion_does_not_access_database_or_sources():
    settings = get_settings().model_copy(update={"ingest_enabled": False})
    assert jobs.run_ingestion(settings=settings) == {"enabled": False}
