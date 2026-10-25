"""Real PostgreSQL/PostGIS and Redis checks, using only temporary test namespaces."""

import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from geoalchemy2 import alembic_helpers
from redis import Redis
from rq import Queue, SimpleWorker
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from alembic import command
from app.core.config import get_settings
from app.db.base import Base
from app.models import Company, CompanyMatch, CompanyMetric, SourceRecord
from app.workers.jobs import heartbeat
from ingestion.loader import load_bundle, load_companies, read_bundle
from ingestion.normalize import RawCompany
from modules.deal_calculator.seed import DEFAULT_BUNDLE
from modules.deal_calculator.seed import load_bundle as load_calculator_bundle

pytestmark = pytest.mark.integration
BACKEND = Path(__file__).resolve().parents[1]


def require_service(error):
    if os.environ.get("REQUIRE_INTEGRATION") == "1":
        pytest.fail(f"Integration service unavailable: {error}")
    pytest.skip(f"Integration service unavailable: {error}")


@pytest.fixture
def isolated_database():
    url = get_settings().database_url
    admin = create_engine(url, connect_args={"connect_timeout": 2})
    namespace = "test_bootstrap_" + uuid.uuid4().hex
    try:
        with admin.begin() as connection:
            connection.execute(CreateSchema(namespace))
    except Exception as error:
        admin.dispose()
        require_service(error)
    engine = create_engine(
        url, connect_args={"connect_timeout": 2, "options": f"-csearch_path={namespace},public"}
    )
    try:
        with engine.connect() as connection:
            config = Config(str(BACKEND / "alembic.ini"))
            config.set_main_option("script_location", str(BACKEND / "alembic"))
            config.attributes["connection"] = connection
            yield engine, connection, config, namespace
    finally:
        engine.dispose()
        with admin.begin() as connection:
            assert namespace.startswith("test_bootstrap_")
            connection.execute(DropSchema(namespace, cascade=True))
        admin.dispose()


def test_migrations_backfill_notifications_and_match_models(isolated_database):
    _, connection, config, namespace = isolated_database
    command.upgrade(config, "20261025_0001")
    user_id = connection.scalar(
        text("""
        INSERT INTO app_user
            (email, login, password_hash, role, totp_enabled, status, failed_login_count)
        VALUES ('migration@example.test', 'migration', 'test-only', 'manager', false, 'active', 0)
        RETURNING id
    """)
    )
    connection.execute(
        text("""
        INSERT INTO notification (user_id, type, payload_json, dedup_key, channel)
        VALUES (:user_id, 'test', '{}', 'migration-event', 'in_app'),
               (:user_id, 'test', '{}', 'migration-event', 'in_app')
    """),
        {"user_id": user_id},
    )
    connection.execute(
        text("""INSERT INTO refresh_token (jti, user_id, expires_at)
        VALUES ('legacy-refresh-token', :user_id, now() + INTERVAL '1 day')"""),
        {"user_id": user_id},
    )
    connection.execute(
        text("""INSERT INTO partial_auth (token_id, user_id, scope, expires_at)
        VALUES ('legacy-partial-token', :user_id, 'mfa_pending', now() + INTERVAL '5 minutes')"""),
        {"user_id": user_id},
    )
    connection.commit()
    command.upgrade(config, "head")
    assert connection.scalar(text("SELECT created_at FROM notification LIMIT 1")) is not None
    assert connection.scalar(text("SELECT count(*) FROM notification")) == 2
    assert connection.scalar(text("SELECT revoked_at FROM refresh_token")) is not None
    assert connection.scalar(text("SELECT count(*) FROM partial_auth")) == 0
    assert set(Base.metadata.tables) <= set(inspect(connection).get_table_names(schema=namespace))
    context = MigrationContext.configure(
        connection, opts={"include_object": alembic_helpers.include_object, "compare_type": True}
    )
    assert compare_metadata(context, Base.metadata) == []
    connection.commit()
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    assert set(inspect(connection).get_table_names(schema=namespace)) == {"alembic_version"}
    connection.commit()
    command.upgrade(config, "head")


@pytest.mark.parametrize("operation", ["totp", "backup", "refresh", "logout_refresh"])
def test_auth_secrets_are_not_reused_by_parallel_requests(isolated_database, operation):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, timedelta
    from threading import Barrier

    import pyotp

    from app.core.security import encrypt_secret, hash_backup_codes
    from app.models import PartialAuth, RefreshToken, User
    from modules.auth import service as auth

    engine, _, config, _ = isolated_database
    command.upgrade(config, "head")
    secret, backup = pyotp.random_base32(), "A1B2C3D4"
    code = pyotp.TOTP(secret).now()
    with Session(engine) as session:
        user = User(
            email="race@example.test",
            login="race",
            password_hash="not-used",
            role="manager",
            totp_enabled=True,
            totp_secret_encrypted=encrypt_secret(secret),
            backup_codes_hash=hash_backup_codes([backup]),
        )
        session.add(user)
        session.flush()
        partials = [uuid.uuid4().hex for _ in range(2)]
        for token in partials:
            session.add(
                PartialAuth(
                    token_id=token,
                    user_id=user.id,
                    auth_version=user.auth_version,
                    scope="mfa_pending",
                    expires_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            )
        tokens = (
            auth._issue_tokens(session, user, None)
            if operation in ("refresh", "logout_refresh")
            else None
        )
        session.commit()
    barrier = Barrier(2)

    def attempt(index):
        with Session(engine) as session:
            barrier.wait(timeout=10)
            try:
                if operation == "logout_refresh" and index == 0:
                    auth.logout(session, tokens.refresh_token, tokens.csrf_token, None)
                elif operation in ("refresh", "logout_refresh"):
                    auth.rotate_refresh(session, tokens.refresh_token, tokens.csrf_token, None)
                else:
                    auth.confirm_2fa(
                        session, partials[index], code if operation == "totp" else backup, None
                    )
                session.commit()
                return True
            except PermissionError:
                session.commit()
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    with Session(engine) as session:
        active = session.scalar(
            select(func.count(RefreshToken.jti)).where(RefreshToken.revoked_at.is_(None))
        )
    if operation == "logout_refresh":
        assert results[0] and active == 0
    else:
        assert sorted(results) == [False, True] and active == 1


def test_both_seeds_are_repeatable_including_sources_and_matches(isolated_database):
    engine, connection, config, _ = isolated_database
    command.upgrade(config, "head")
    bundle = read_bundle(get_settings().demo_bundle_path)
    calculator_bundle = json.loads(DEFAULT_BUNDLE.read_text(encoding="utf-8"))
    with Session(engine) as session:
        load_bundle(session, bundle)
        session.commit()
        load_calculator_bundle(session, calculator_bundle)
        models = (Company, CompanyMetric, CompanyMatch, SourceRecord)
        before = [session.scalar(select(func.count()).select_from(model)) for model in models]
        load_bundle(session, bundle)
        session.commit()
        second_calculator = load_calculator_bundle(session, calculator_bundle)
        after = [session.scalar(select(func.count()).select_from(model)) for model in models]
    assert before == after
    assert before[0] == 48
    assert second_calculator["deals"] == second_calculator["positions"] == 0


def test_matching_keeps_distinct_inns_and_regions_separate(isolated_database):
    engine, _, config, _ = isolated_database
    command.upgrade(config, "head")
    from app.models import Region

    with Session(engine) as session:
        first = Region(name="First", code="TEST-FIRST")
        second = Region(name="Second", code="TEST-SECOND")
        session.add_all([first, second])
        session.flush()
        regions = {first.code: first.id, second.code: second.id}
        records = [
            RawCompany(
                source="test",
                external_id="1",
                name="Same",
                inn="7710137066",
                region_code=first.code,
            ),
            RawCompany(
                source="test",
                external_id="2",
                name="Same",
                inn="7707083893",
                region_code=first.code,
            ),
            RawCompany(
                source="test", external_id="3", name="No identifier", region_code=first.code
            ),
            RawCompany(
                source="test", external_id="4", name="No identifier", region_code=second.code
            ),
        ]
        load_companies(session, records, {}, regions)
        session.commit()
        load_companies(session, records, {}, regions)
        session.commit()
        assert session.scalar(select(func.count(Company.id))) == 4
        assert session.scalar(select(func.count(CompanyMatch.id))) == 4


def test_rq_executes_a_serialized_job():
    redis = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        redis.ping()
    except Exception as error:
        require_service(error)
    queue = Queue("test-bootstrap-" + uuid.uuid4().hex, connection=redis)
    try:
        job = queue.enqueue(heartbeat)
        worker = SimpleWorker([queue], connection=redis)
        if sys.platform == "win32":
            from rq.timeouts import TimerDeathPenalty

            worker.death_penalty_class = TimerDeathPenalty
        worker.work(burst=True)
        job.refresh()
        assert job.is_finished
        assert datetime.fromisoformat(job.return_value()).tzinfo is not None
    finally:
        queue.delete(delete_jobs=True)
        redis.close()


def test_case_import_and_radar_on_migrated_postgis_schema(isolated_database):
    from app.models import InvestmentProject
    from ingestion.case_workbook import import_case
    from modules.radar import service as radar

    engine, _, config, _ = isolated_database
    command.upgrade(config, "head")
    with Session(engine) as session:
        first = import_case(session, get_settings().case_workbook_path)
        session.commit()
        second = import_case(session, get_settings().case_workbook_path)
        session.commit()
        assert first["accepted_companies"] == 759 and first["accepted_projects"] == 63
        assert first["rejected_rows"] == 0
        assert second["companies_created"] == second["projects_created"] == 0
        assert session.scalar(select(func.count(InvestmentProject.id))) == 63
        assert session.scalar(select(func.count(Company.id))) == 819
        assert sum(c.companies_count for c in radar.heatmap(session)) == 819
        assert radar.white_spaces(session) == []


def test_real_materialized_views_are_populated_and_used(isolated_database, monkeypatch):
    from modules.radar import service as radar
    from modules.readmodels import service as readmodels

    engine, _, config, namespace = isolated_database
    command.upgrade(config, "head")
    with Session(engine) as session:
        load_bundle(session, read_bundle(get_settings().demo_bundle_path))
        session.commit()
        before = radar.heatmap(session)
        assert readmodels.rebuild(session) == 7
        session.commit()
        views = session.scalars(
            text("SELECT matviewname FROM pg_matviews WHERE schemaname=:namespace"),
            {"namespace": namespace},
        ).all()
        assert set(views) == set(readmodels.VIEWS.values())
        assert session.scalar(text("SELECT count(*) FROM mv_region_density")) == 2
        monkeypatch.setattr(radar, "_cells", lambda *args, **kw: pytest.fail("live recompute"))
        cached = radar.heatmap(session)
        assert [(r.region_id, r.potential_score) for r in cached] == [
            (r.region_id, r.potential_score) for r in before
        ]


def test_notification_delivery_is_atomic_with_concurrent_workers(isolated_database):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, timedelta
    from threading import Barrier

    from app.models import Notification, NotificationReceipt, Subscription, User
    from modules.notifications.events import emit
    from modules.notifications.service import dispatch

    engine, _, config, _ = isolated_database
    command.upgrade(config, "head")
    with Session(engine) as session:
        user = User(email="notify@test.local", login="notify", role="manager", password_hash="test")
        session.add(user)
        session.flush()
        session.add(
            Subscription(
                user_id=user.id,
                module="investments",
                filters_json={},
                notify_frequency="immediate",
                created_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        for i in range(100):
            emit(session, "investments", i, "investment.new", "1", {"title": str(i)})
        session.commit()
    barrier = Barrier(2)

    def deliver(_):
        with Session(engine) as session:
            barrier.wait(timeout=10)
            count = dispatch(session)
            session.commit()
            return count

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(deliver, range(2))) == 100
    with Session(engine) as session:
        assert session.scalar(select(func.count(Notification.id))) == 100
        assert session.scalar(select(func.count(NotificationReceipt.event_id))) == 100


def test_concurrent_export_jobs_claim_task_once(isolated_database, monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.orm import sessionmaker

    from app.models import BackgroundTask, User
    from app.schemas import ExportCsvRequest
    from modules.exports import tasks

    engine, _, config, _ = isolated_database
    command.upgrade(config, "head")
    monkeypatch.setattr(get_settings(), "export_dir", str(tmp_path))
    with Session(engine) as session:
        user = User(email="export@test.local", login="export", role="manager", password_hash="test")
        session.add(user)
        session.flush()
        task = tasks.create(session, user.id, ExportCsvRequest(module="companies"))
        task_id = task.id
        session.commit()
    barrier = Barrier(2)

    def generate(_):
        barrier.wait(timeout=10)
        return tasks.generate(task_id, session_factory=sessionmaker(engine))

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(generate, range(2))) == [False, True]
    with Session(engine) as session:
        task = session.get(BackgroundTask, task_id)
        assert task.status == "done" and task.attempts == 1
    assert len(list(tmp_path.glob("*.csv"))) == 1
