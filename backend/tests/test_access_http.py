"""Authorization matrix and object ownership for both calculator/export APIs."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_token, issue_access_token
from app.db.session import get_session
from app.main import app
from app.models import AuditLog, Company, Deal, DealEstimate, InvestmentProject, User
from modules.deal_calculator.models import CalcEstimate


@pytest.fixture
def access_api(business_db, authenticated_session, monkeypatch, tmp_path):
    session, engine = business_db
    monkeypatch.setattr(get_settings(), "export_dir", str(tmp_path))
    users, tokens, estimates = {}, {}, {}
    for login, role in (
        ("owner", "manager"),
        ("other", "manager"),
        ("analyst", "analyst"),
        ("admin", "admin"),
    ):
        user = User(email=f"{login}@example.test", login=login, password_hash="test", role=role)
        session.add(user)
        session.flush()
        users[login] = user.id
        tokens[login] = authenticated_session(session, user).access_token
    for name in ("owner", "analyst", "orphan"):
        row = CalcEstimate(
            author_id=users.get(name),
            request_json={},
            price_min=110,
            price_optimum=120,
            price_max=150,
            cost_total=100,
            estimator_mode="rule_based",
            data_quality="limited",
            model_version="test",
            comparables_json=[],
            adjustments_json=[],
            cost_json={"total": 100},
        )
        session.add(row)
        session.flush()
        estimates[name] = row.id
    deal = Deal(author_id=users["owner"], input_params_json={})
    session.add(deal)
    session.flush()
    legacy = DealEstimate(
        deal_id=deal.id, price_min=100, price_optimum=120, price_max=150, model_version="test"
    )
    session.add(legacy)
    session.commit()
    legacy_id = legacy.id

    def database():
        with Session(engine) as request_session:
            try:
                yield request_session
            except Exception:
                request_session.rollback()
                raise

    app.dependency_overrides[get_session] = database
    try:
        with TestClient(app) as client:
            yield client, session, users, tokens, estimates, legacy_id
    finally:
        app.dependency_overrides.pop(get_session, None)


def auth(tokens, name):
    return {"Authorization": f"Bearer {tokens[name]}"}


@pytest.mark.parametrize(
    "name,target,expected",
    [
        ("owner", "owner", 200),
        ("other", "owner", 404),
        ("analyst", "analyst", 403),
        ("admin", "owner", 200),
        ("admin", "orphan", 200),
        ("owner", "orphan", 404),
    ],
)
def test_approval_checks_role_and_owner_before_mutation(access_api, name, target, expected):
    client, session, users, tokens, estimates, _ = access_api
    response = client.post(
        f"/api/v1/calculator/estimates/{estimates[target]}/approve",
        headers=auth(tokens, name),
        json={"price": 130},
    )
    assert response.status_code == expected, response.text
    session.expire_all()
    row = session.get(CalcEstimate, estimates[target])
    if expected == 200:
        assert row.approved_price == Decimal(130) and row.approved_by == users[name]
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "calculator.approve"))
        assert audit and audit.before_hash != audit.after_hash
    else:
        assert row.approved_price is None and row.approved_by is None


@pytest.mark.parametrize(
    "suffix",
    ["csv", "csv?kind=crm", "csv?kind=comparables", "proposal", "proposal?variant=internal"],
)
def test_foreign_estimate_exports_are_hidden(access_api, suffix):
    client, session, _, tokens, estimates, _ = access_api
    response = client.get(
        f"/api/v1/calculator/estimates/{estimates['owner']}/{suffix}", headers=auth(tokens, "other")
    )
    assert response.status_code == 404
    assert session.scalar(select(func.count(AuditLog.id))) == 0


@pytest.mark.parametrize("estimate_id", [0, -1, 999999])
def test_missing_id_cannot_export_all_estimates(access_api, estimate_id):
    client, _, _, tokens, _, _ = access_api
    assert (
        client.get(
            f"/api/v1/calculator/estimates/{estimate_id}/csv", headers=auth(tokens, "admin")
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "name,target,variant,expected",
    [
        ("owner", "owner", "client", 200),
        ("owner", "owner", "internal", 403),
        ("analyst", "analyst", "internal", 200),
        ("admin", "owner", "internal", 200),
    ],
)
def test_internal_proposal_is_a_separate_permission(access_api, name, target, variant, expected):
    client, _, _, tokens, estimates, _ = access_api
    response = client.get(
        f"/api/v1/calculator/estimates/{estimates[target]}/proposal",
        params={"variant": variant},
        headers=auth(tokens, name),
    )
    assert response.status_code == expected, response.text if expected != 200 else ""


def test_legacy_proposal_generation_and_download_use_same_ownership(access_api):
    client, _, _, tokens, _, legacy_id = access_api
    for name in ("other", "analyst"):
        assert (
            client.post(
                "/api/v1/exports/proposal",
                params={"estimate_id": legacy_id},
                headers=auth(tokens, name),
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"/api/v1/exports/proposal/{legacy_id}/download", headers=auth(tokens, name)
            ).status_code
            == 404
        )
    created = client.post(
        "/api/v1/exports/proposal", params={"estimate_id": legacy_id}, headers=auth(tokens, "owner")
    )
    assert created.status_code == 200 and "file_ref" not in created.json()
    assert (
        client.get(created.json()["download_url"], headers=auth(tokens, "admin")).status_code == 200
    )
    assert (
        client.get(created.json()["download_url"], headers=auth(tokens, "other")).status_code == 404
    )


def test_database_role_wins_over_old_or_forged_role_claim(access_api):
    client, session, users, tokens, estimates, _ = access_api
    claims = decode_token(tokens["other"])
    forged_role = issue_access_token(
        users["other"],
        "admin",
        session_id=claims["sid"],
        auth_version=claims["v"],
        mfa_method="otp",
    )
    assert (
        client.get("/api/v1/audit", headers={"Authorization": f"Bearer {forged_role}"}).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/calculator/estimates/{estimates['owner']}/csv",
            headers={"Authorization": f"Bearer {forged_role}"},
        ).status_code
        == 404
    )
    session.get(User, users["owner"]).role = "analyst"
    session.commit()
    assert (
        client.post(
            f"/api/v1/calculator/estimates/{estimates['owner']}/approve",
            json={"price": 130},
            headers=auth(tokens, "owner"),
        ).status_code
        == 403
    )


def test_admin_audit_is_paginated_and_records_empty_estimate_too(access_api):
    client, session, users, tokens, _, _ = access_api
    response = client.post("/api/v1/calculator/estimate", json={}, headers=auth(tokens, "owner"))
    assert response.status_code == 200, response.text
    estimate_id = response.json()["estimate_id"]
    assert session.get(CalcEstimate, estimate_id).author_id == users["owner"]
    for name in ("owner", "analyst"):
        assert client.get("/api/v1/audit", headers=auth(tokens, name)).status_code == 403
    audit = client.get(
        "/api/v1/audit",
        params={"action": "calculator.estimate", "limit": 1},
        headers=auth(tokens, "admin"),
    )
    assert audit.status_code == 200 and len(audit.json()) == 1
    assert audit.json()[0]["object_id"] == str(estimate_id)
    assert audit.json()[0]["after_hash"]


def test_calculator_rejects_missing_or_inconsistent_links(access_api):
    client, session, _, tokens, _, _ = access_api
    for field, expected in (
        ("company_id", 404),
        ("investment_project_id", 404),
        ("region_id", 422),
    ):
        assert (
            client.post(
                "/api/v1/calculator/estimate", json={field: 999999}, headers=auth(tokens, "owner")
            ).status_code
            == expected
        )
    first = Company(name="First", name_normalized="first")
    second = Company(name="Second", name_normalized="second")
    session.add_all([first, second])
    session.flush()
    project = InvestmentProject(title="Project", stage="unknown", initiator_company_id=first.id)
    session.add(project)
    session.commit()
    response = client.post(
        "/api/v1/calculator/estimate",
        json={
            "investment_project_id": project.id,
            "company_id": second.id,
        },
        headers=auth(tokens, "owner"),
    )
    assert response.status_code == 422
