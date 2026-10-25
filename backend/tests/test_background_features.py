"""Durable notifications, private preferences and streaming export recovery."""

import csv
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.session import get_session
from app.main import app
from app.models import (
    BackgroundTask,
    Company,
    DomainEvent,
    Notification,
    NotificationReceipt,
    SavedFilter,
    Subscription,
    User,
)
from modules.exports import tasks
from modules.notifications import events
from modules.notifications import service as notifications


@pytest.fixture
def feature_api(business_db, authenticated_session, monkeypatch, tmp_path):
    session, engine = business_db
    monkeypatch.setattr(get_settings(), "export_dir", str(tmp_path))
    users, tokens = {}, {}
    for name, role in (("owner", "manager"), ("other", "analyst"), ("admin", "admin")):
        user = User(email=f"{name}@test.local", login=name, role=role, password_hash="test")
        session.add(user)
        session.flush()
        users[name] = user.id
        tokens[name] = authenticated_session(session, user).access_token

    def database():
        with Session(engine) as request_session:
            yield request_session

    app.dependency_overrides[get_session] = database
    try:
        with TestClient(app) as client:
            client.headers["Authorization"] = f"Bearer {tokens['owner']}"
            yield client, session, engine, users, tokens
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_saved_filter_defaults_are_per_user_and_module(feature_api):
    client, session, _, _, tokens = feature_api
    payload = {
        "module": "companies",
        "name": "Ростов",
        "filters": {"region_id": 1},
        "is_default": True,
    }
    first = client.post("/api/v1/saved-filters", json=payload)
    second = client.post("/api/v1/saved-filters", json={**payload, "name": "Другой"})
    assert first.status_code == second.status_code == 201
    rows = client.get("/api/v1/saved-filters").json()
    assert [r["is_default"] for r in rows] == [False, True]
    result = client.patch(
        f"/api/v1/saved-filters/{first.json()['id']}",
        json={"is_default": True, "filters": {"q": "ОАО"}},
    )
    assert result.status_code == 200 and result.json()["filters_json"] == {"q": "ОАО"}
    assert [r["is_default"] for r in client.get("/api/v1/saved-filters").json()] == [True, False]
    for name in ("other", "admin"):
        headers = {"Authorization": f"Bearer {tokens[name]}"}
        assert client.get("/api/v1/saved-filters", headers=headers).json() == []
        for method in (client.patch, client.delete):
            kwargs = {"json": {"name": "foreign"}} if method == client.patch else {}
            assert (
                method(
                    f"/api/v1/saved-filters/{first.json()['id']}", headers=headers, **kwargs
                ).status_code
                == 404
            )
    assert client.delete(f"/api/v1/saved-filters/{second.json()['id']}").status_code == 200
    session.expire_all()
    assert session.scalar(select(func.count(SavedFilter.id))) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"module": "unknown", "name": "x"},
        {"module": "companies", "name": " "},
        {"module": "companies", "name": "x", "filters": {"limit": 100}},
        {"module": "investments", "name": "x", "filters": {"region_id": -1}},
    ],
)
def test_invalid_saved_filters_are_rejected(feature_api, body):
    assert feature_api[0].post("/api/v1/saved-filters", json=body).status_code == 422


def test_subscriptions_validate_filters_and_hide_foreign_rows(feature_api):
    client, session, _, _, tokens = feature_api
    invalid = {"module": "investments", "filters": {"unknown": True}}
    assert client.post("/api/v1/subscriptions", json=invalid).status_code == 422
    assert (
        client.post(
            "/api/v1/subscriptions", json={"module": "tenders", "notify_frequency": "sometimes"}
        ).status_code
        == 422
    )
    result = client.post(
        "/api/v1/subscriptions",
        json={
            "module": "investments",
            "notify_frequency": "hourly",
            "filters": {"stage": "design"},
        },
    )
    assert result.status_code == 200
    sub_id = result.json()["id"]
    assert (
        client.patch(f"/api/v1/subscriptions/{sub_id}", json={"filters": None}).status_code == 422
    )
    headers = {"Authorization": f"Bearer {tokens['other']}"}
    assert (
        client.patch(
            f"/api/v1/subscriptions/{sub_id}", headers=headers, json={"is_active": False}
        ).status_code
        == 404
    )
    assert (
        client.patch(f"/api/v1/subscriptions/{sub_id}", json={"is_active": False}).status_code
        == 200
    )
    assert client.get("/api/v1/subscriptions?limit=0").status_code == 422
    assert client.delete(f"/api/v1/subscriptions/{sub_id}").status_code == 200
    session.expire_all()
    assert session.get(Subscription, sub_id) is None


def subscriber(session, *, frequency="immediate", filters=None, start=None, active=True):
    user = User(
        email=f"u{len(session.identity_map)}-{datetime.now().timestamp()}@test.local",
        login=f"u{datetime.now().timestamp()}",
        role="manager",
        password_hash="test",
        status="active" if active else "blocked",
    )
    session.add(user)
    session.flush()
    sub = Subscription(
        user_id=user.id,
        module="investments",
        filters_json=filters or {},
        notify_frequency=frequency,
        created_at=start or datetime.now(UTC) - timedelta(days=1),
    )
    session.add(sub)
    session.commit()
    return sub


def event(session, number, *, now=None, **payload):
    return events.emit(
        session,
        "investments",
        number,
        "investment.new",
        f"v{number}",
        {"title": f"Проект {number}", "stage": "design", "region_id": 1, **payload},
        now=now,
    )


def test_all_events_are_delivered_once_across_overlapping_subscriptions(business_db):
    session, _ = business_db
    first = subscriber(session)
    session.add(
        Subscription(
            user_id=first.user_id,
            module="investments",
            filters_json={},
            notify_frequency="immediate",
            created_at=first.created_at,
        )
    )
    for number in range(620):
        assert event(session, number) == 1
    assert event(session, 1) == 0
    session.commit()
    assert notifications.dispatch(session) == 620
    session.commit()
    assert notifications.dispatch(session) == 0
    assert session.scalar(select(func.count(Notification.id))) == 620
    assert session.scalar(select(func.count(NotificationReceipt.event_id))) == 1240


@pytest.mark.parametrize(
    "frequency,seconds", [("hourly", 3600), ("daily", 86400), ("weekly", 604800)]
)
def test_delivery_waits_for_frequency_and_rolls_back_atomically(business_db, frequency, seconds):
    session, _ = business_db
    now = datetime.now(UTC)
    sub = subscriber(session, frequency=frequency, start=now - timedelta(days=1))
    event(session, 1, now=now)
    session.commit()
    assert notifications.dispatch(session, now=now) == 1
    session.rollback()
    assert session.scalar(select(func.count(Notification.id))) == 0
    assert session.scalar(select(func.count(NotificationReceipt.event_id))) == 0
    assert notifications.dispatch(session, now=now) == 1
    session.commit()
    event(session, 2, now=now + timedelta(seconds=1))
    session.commit()
    assert notifications.dispatch(session, now=now + timedelta(seconds=seconds - 1)) == 0
    assert notifications.dispatch(session, now=now + timedelta(seconds=seconds)) == 1
    session.commit()
    assert session.get(Subscription, sub.id).last_dispatch_at is not None


def test_filters_subscription_start_and_inactive_users_are_respected(business_db):
    session, _ = business_db
    now = datetime.now(UTC)
    subscriber(session, filters={"stage": "design", "region_id": 1, "q": "проект"}, start=now)
    subscriber(session, start=now, active=False)
    event(session, 1, now=now - timedelta(seconds=1))
    event(session, 2, now=now + timedelta(seconds=1))
    event(session, 3, now=now + timedelta(seconds=1), region_id=2)
    event(session, 4, now=now + timedelta(seconds=1), stage="launch")
    session.commit()
    assert notifications.dispatch(session, now=now + timedelta(seconds=2)) == 1
    session.commit()
    assert session.scalar(select(func.count(NotificationReceipt.event_id))) == 3
    assert session.scalar(select(func.count(Notification.id))) == 1


def test_outbox_and_business_update_share_one_transaction(business_db):
    session, _ = business_db
    company = Company(name="Transient", name_normalized="transient", client_status="unknown")
    session.add(company)
    session.flush()
    event(session, 1)
    session.rollback()
    assert session.scalar(select(func.count(Company.id))) == 0
    assert session.scalar(select(func.count(DomainEvent.id))) == 0


def test_async_export_includes_more_than_5000_rows_and_enforces_ownership(feature_api):
    client, session, engine, _, tokens = feature_api
    session.add_all(
        Company(name=f"Company {i:05}", name_normalized=f"company {i:05}", client_status="unknown")
        for i in range(5003)
    )
    session.commit()
    assert client.post("/api/v1/exports/csv", json={"module": "companies"}).status_code == 413
    response = client.post("/api/v1/exports", json={"module": "companies"})
    assert response.status_code == 202
    body, factory = response.json(), sessionmaker(engine)
    assert body["status"] == "pending" and body["download_url"] is None
    assert client.get(f"/api/v1/exports/{body['id']}/download").status_code == 409
    assert tasks.generate(body["id"], session_factory=factory)
    assert not tasks.generate(body["id"], session_factory=factory)
    status = client.get(body["status_url"])
    assert status.json()["status"] == "done" and status.json()["attempts"] == 1
    assert "file_ref" not in status.json() and "params" not in status.json()
    download_url = status.json()["download_url"]
    foreign = {"Authorization": f"Bearer {tokens['other']}"}
    assert client.get(body["status_url"], headers=foreign).status_code == 404
    assert client.get(download_url, headers=foreign).status_code == 404
    response = client.get(download_url)
    assert response.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(rows) == 5004 and rows[-1][1] == "Company 05002"
    assert (
        client.get(download_url, headers={"Authorization": f"Bearer {tokens['admin']}"}).status_code
        == 200
    )


def test_export_failure_retries_and_reclaims_expired_lease(feature_api, monkeypatch):
    client, session, engine, _, _ = feature_api
    body = client.post("/api/v1/exports", json={"module": "companies"}).json()
    factory = sessionmaker(engine)
    actual = tasks.service.companies_rows
    monkeypatch.setattr(tasks.service, "companies_rows", Mock(side_effect=OSError("private-path")))
    with pytest.raises(OSError):
        tasks.generate(body["id"], session_factory=factory)
    session.expire_all()
    row = session.get(BackgroundTask, body["id"])
    assert row.status == "pending" and row.attempts == 1 and row.file_ref is None
    assert "private-path" not in row.error
    assert list(Path(get_settings().export_dir).iterdir()) == []
    row.status, row.lease_token = "running", "abandoned"
    row.lease_until = datetime.now(UTC) + timedelta(hours=1)
    session.commit()
    assert not tasks.generate(row.id, session_factory=factory)
    row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    monkeypatch.setattr(tasks.service, "companies_rows", actual)
    assert tasks.generate(row.id, session_factory=factory)
    session.expire_all()
    assert session.get(BackgroundTask, row.id).attempts == 2


def test_export_attempts_are_bounded_and_paths_cannot_escape(feature_api, monkeypatch, tmp_path):
    client, session, engine, _, _ = feature_api
    task = client.post("/api/v1/exports", json={"module": "companies"}).json()
    monkeypatch.setattr(tasks.service, "companies_rows", Mock(side_effect=RuntimeError("secret")))
    for _ in range(3):
        with pytest.raises(RuntimeError):
            tasks.generate(task["id"], session_factory=sessionmaker(engine))
    assert not tasks.generate(task["id"], session_factory=sessionmaker(engine))
    result = client.get(task["status_url"]).json()
    assert result["status"] == "failed" and result["attempts"] == 3
    assert "secret" not in result["error"]
    session.expire_all()
    row = session.get(BackgroundTask, task["id"])
    outside = tmp_path.parent / "outside.csv"
    outside.write_text("private", encoding="utf-8")
    row.status, row.file_ref = "done", str(outside)
    session.commit()
    assert client.get(f"/api/v1/exports/{row.id}/download").status_code == 404
