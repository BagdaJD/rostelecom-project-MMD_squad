"""Authentication through HTTP: enrollment, replay, cookies, CSRF and revocation."""

from datetime import UTC, datetime, timedelta

import pyotp
import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.auth import CSRF_COOKIE, REFRESH_COOKIE
from app.core import ratelimit
from app.core.config import get_settings
from app.core.security import (
    decode_token,
    decrypt_secret,
    encrypt_secret,
    hash_backup_codes,
    issue_access_token,
    token_hash,
)
from app.db.session import get_session
from app.main import app
from app.models import AuditLog, PartialAuth, RefreshToken, User
from modules.auth import service as auth

PASSWORD = "correct-horse-test-password"
BACKUPS = ["A1B2C3D4", "1234ABCD"]


@pytest.fixture
def auth_api(business_db, monkeypatch):
    session, engine = business_db
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "test")
    monkeypatch.setattr(settings, "auth_cookie_secure", True)
    ratelimit._memory.clear()

    def unavailable():
        raise redis.ConnectionError("test Redis unavailable")

    monkeypatch.setattr(ratelimit, "_redis", unavailable)
    clock = [datetime.now(UTC).replace(microsecond=0)]
    monkeypatch.setattr(auth, "_now", lambda: clock[0])
    secret = pyotp.random_base32()
    user = auth.create_user(session, "auth@example.test", "auth", PASSWORD, "manager")
    user.totp_enabled = True
    user.totp_secret_encrypted = encrypt_secret(secret)
    user.backup_codes_hash = hash_backup_codes(BACKUPS)
    session.commit()
    user_id = user.id

    def database():
        with Session(engine) as request_session:
            try:
                yield request_session
            except Exception:
                request_session.rollback()
                raise

    app.dependency_overrides[get_session] = database
    try:
        with TestClient(app, base_url="https://testserver") as client:
            yield client, session, user_id, secret, clock
    finally:
        app.dependency_overrides.pop(get_session, None)
        ratelimit._memory.clear()


def challenge(client):
    response = client.post("/api/v1/auth/login", json={"login": "auth", "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["partial_token"]


def verify(client, partial, code):
    return client.post("/api/v1/auth/2fa/verify", json={"partial_token": partial, "code": code})


def login(client, secret, clock):
    result = verify(client, challenge(client), pyotp.TOTP(secret).at(clock[0]))
    assert result.status_code == 200, result.text
    return result


def headers(access):
    return {"Authorization": f"Bearer {access}"}


def test_password_alone_and_unsigned_session_claims_cannot_access_api(auth_api):
    client, _, user_id, _, _ = auth_api
    pending = client.post("/api/v1/auth/login", json={"login": "auth", "password": PASSWORD})
    assert pending.status_code == 200
    assert pending.json()["mfa_required"] and not pending.json()["mfa_setup_required"]
    assert "access_token" not in pending.json() and "refresh_token" not in pending.json()
    assert REFRESH_COOKIE not in client.cookies
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.get("/api/v1/auth/me", headers=headers(pending.json()["partial_token"])).status_code
        == 401
    )
    assert (
        client.get(
            "/api/v1/auth/me",
            headers=headers(issue_access_token(user_id, "admin", scope="mfa_pending")),
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/auth/me", headers=headers(issue_access_token(user_id, "admin"))
        ).status_code
        == 401
    )


def test_enrollment_requires_proof_and_returns_backup_codes_once(auth_api):
    client, session, user_id, _, clock = auth_api
    auth.disable_2fa(session, session.get(User, user_id))
    session.commit()
    pending = client.post("/api/v1/auth/login", json={"login": "auth", "password": PASSWORD}).json()
    assert pending["mfa_required"] and pending["mfa_setup_required"]
    partial = pending["partial_token"]
    setup = client.post("/api/v1/auth/2fa/setup", json={"partial_token": partial})
    assert setup.status_code == 200 and "backup_codes" not in setup.json()
    secret = setup.json()["secret"]
    assert "otpauth://totp/" in setup.json()["otpauth_hint"]
    session.expire_all()
    assert not session.get(User, user_id).totp_enabled
    assert client.post("/api/v1/auth/2fa/setup", json={"partial_token": partial}).status_code == 409
    response = verify(client, partial, pyotp.TOTP(secret).at(clock[0]))
    assert response.status_code == 200, response.text
    assert len(response.json()["backup_codes"]) == 8
    session.expire_all()
    user = session.get(User, user_id)
    assert user.totp_enabled and decrypt_secret(user.totp_secret_encrypted) == secret
    assert secret not in user.totp_secret_encrypted
    assert all(code not in user.backup_codes_hash for code in response.json()["backup_codes"])
    token = response.json()["access_token"]
    assert client.get("/api/v1/auth/me", headers=headers(token)).status_code == 200
    assert verify(client, partial, pyotp.TOTP(secret).at(clock[0])).status_code == 401
    assert client.post("/api/v1/auth/2fa/disable", headers=headers(token)).status_code == 409
    assert client.get("/api/v1/auth/me", headers=headers(token)).status_code == 200


def test_cookie_flags_hash_storage_and_auth_cache_control(auth_api):
    client, session, user_id, secret, clock = auth_api
    response = login(client, secret, clock)
    assert "refresh_token" not in response.json()
    cookie = next(
        c for c in response.headers.get_list("set-cookie") if c.startswith(REFRESH_COOKIE + "=")
    )
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert response.headers["cache-control"] == "no-store"
    raw = client.cookies.get(REFRESH_COOKIE)
    row = session.get(RefreshToken, token_hash(raw))
    assert row is not None and row.jti != raw and row.user_id == user_id
    assert row.csrf_hash == token_hash(response.json()["csrf_token"])
    claims = decode_token(response.json()["access_token"])
    assert claims["sid"] == row.jti and claims["amr"] == ["pwd", "otp"]
    assert session.scalar(select(func.count(PartialAuth.token_id))) == 0


def test_partial_and_totp_replay_are_rejected(auth_api):
    client, _, _, secret, clock = auth_api
    partial = challenge(client)
    code = pyotp.TOTP(secret).at(clock[0])
    assert verify(client, partial, code).status_code == 200
    assert verify(client, partial, code).status_code == 401
    assert verify(client, challenge(client), code).status_code == 401


def test_backup_codes_are_single_use_across_different_challenges(auth_api):
    client, session, user_id, _, _ = auth_api
    first = verify(client, challenge(client), BACKUPS[0])
    assert first.status_code == 200 and first.json()["backup_codes"] is None
    assert decode_token(first.json()["access_token"])["amr"] == ["pwd", "recovery"]
    partial = challenge(client)
    assert verify(client, partial, BACKUPS[0]).status_code == 401
    assert verify(client, partial, BACKUPS[1].lower()).status_code == 200
    session.expire_all()
    assert session.get(User, user_id).backup_codes_hash is None


def test_failed_mfa_cannot_be_reset_by_new_password_challenges(auth_api):
    client, session, user_id, secret, clock = auth_api
    bad = "111111" if pyotp.TOTP(secret).at(clock[0]) != "111111" else "222222"
    for _ in range(5):
        partial = challenge(client)
        assert verify(client, partial, bad).status_code == 401
    session.expire_all()
    assert session.get(User, user_id).locked_until is not None
    assert (
        client.post("/api/v1/auth/login", json={"login": "auth", "password": PASSWORD}).status_code
        == 401
    )
    assert verify(client, partial, pyotp.TOTP(secret).at(clock[0])).status_code == 401
    clock[0] += timedelta(minutes=16)
    assert login(client, secret, clock).status_code == 200


def test_expired_challenge_and_deactivated_account_are_rejected(auth_api):
    client, session, user_id, secret, clock = auth_api
    partial = challenge(client)
    session.get(PartialAuth, partial).expires_at = clock[0] - timedelta(seconds=1)
    session.commit()
    assert verify(client, partial, pyotp.TOTP(secret).at(clock[0])).status_code == 401
    partial = challenge(client)
    session.get(User, user_id).status = "disabled"
    session.commit()
    assert verify(client, partial, pyotp.TOTP(secret).at(clock[0])).status_code == 401
    assert session.scalar(select(func.count(RefreshToken.jti))) == 0


def test_rotation_is_one_use_and_revokes_old_access(auth_api):
    client, session, _, secret, clock = auth_api
    signed_in = login(client, secret, clock).json()
    raw, csrf = client.cookies.get(REFRESH_COOKIE), client.cookies.get(CSRF_COOKIE)
    refreshed = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert refreshed.status_code == 200, refreshed.text
    assert client.cookies.get(REFRESH_COOKIE) != raw
    assert (
        client.get("/api/v1/auth/me", headers=headers(signed_in["access_token"])).status_code == 401
    )
    access = refreshed.json()["access_token"]
    assert client.get("/api/v1/auth/me", headers=headers(access)).status_code == 200
    replay = client.post(
        "/api/v1/auth/refresh",
        headers={
            "Cookie": f"{REFRESH_COOKIE}={raw}; {CSRF_COOKIE}={csrf}",
            "X-CSRF-Token": csrf,
        },
    )
    assert replay.status_code == 401
    assert session.scalar(select(func.count(RefreshToken.jti))) == 2
    assert client.get("/api/v1/auth/me", headers=headers(access)).status_code == 200


def test_csrf_missing_or_foreign_origin_does_not_revoke_session(auth_api):
    client, _, _, secret, clock = auth_api
    signed_in = login(client, secret, clock).json()
    csrf = client.cookies.get(CSRF_COOKIE)
    assert client.post("/api/v1/auth/refresh").status_code == 403
    assert (
        client.post("/api/v1/auth/refresh", headers=[(b"X-CSRF-Token", b"\xff" * 43)]).status_code
        == 403
    )
    assert client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert (
        client.post(
            "/api/v1/auth/refresh",
            headers={
                "X-CSRF-Token": csrf,
                "Origin": "https://evil.example",
            },
        ).status_code
        == 403
    )
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert (
        client.get("/api/v1/auth/me", headers=headers(signed_in["access_token"])).status_code == 200
    )


def test_logout_revokes_access_and_clears_both_cookies(auth_api):
    client, _, _, secret, clock = auth_api
    signed_in = login(client, secret, clock).json()
    csrf = client.cookies.get(CSRF_COOKIE)
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert REFRESH_COOKIE not in client.cookies and CSRF_COOKIE not in client.cookies
    assert (
        client.get("/api/v1/auth/me", headers=headers(signed_in["access_token"])).status_code == 401
    )
    assert client.post("/api/v1/auth/logout").status_code == 200


def test_query_refresh_is_not_accepted(auth_api):
    client, _, _, secret, clock = auth_api
    login(client, secret, clock)
    raw, csrf = client.cookies.get(REFRESH_COOKIE), client.cookies.get(CSRF_COOKIE)
    client.cookies.delete(REFRESH_COOKIE)
    assert (
        client.post(
            "/api/v1/auth/refresh", params={"refresh_token": raw}, headers={"X-CSRF-Token": csrf}
        ).status_code
        == 401
    )


def test_logout_with_old_cookie_also_revokes_already_rotated_session(auth_api):
    client, _, _, secret, clock = auth_api
    login(client, secret, clock)
    old_raw, old_csrf = client.cookies.get(REFRESH_COOKIE), client.cookies.get(CSRF_COOKIE)
    rotated = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": old_csrf})
    assert rotated.status_code == 200
    response = client.post(
        "/api/v1/auth/logout",
        headers={
            "Cookie": f"{REFRESH_COOKIE}={old_raw}; {CSRF_COOKIE}={old_csrf}",
            "X-CSRF-Token": old_csrf,
        },
    )
    assert response.status_code == 200
    assert (
        client.get("/api/v1/auth/me", headers=headers(rotated.json()["access_token"])).status_code
        == 401
    )


def test_factor_reset_revokes_existing_sessions_and_pending_logins(auth_api):
    client, session, user_id, secret, clock = auth_api
    result = login(client, secret, clock).json()
    partial = challenge(client)
    auth.disable_2fa(session, session.get(User, user_id))
    session.commit()
    assert client.get("/api/v1/auth/me", headers=headers(result["access_token"])).status_code == 403
    assert verify(client, partial, BACKUPS[0]).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/refresh", headers={"X-CSRF-Token": result["csrf_token"]}
        ).status_code
        == 401
    )


def test_auth_audit_contains_no_credentials_or_session_secrets(auth_api):
    client, session, _, secret, clock = auth_api
    result = login(client, secret, clock).json()
    rows = session.scalars(select(AuditLog)).all()
    assert {row.action for row in rows} >= {"login.mfa_pending", "mfa.success"}
    rendered = str([{c.name: getattr(row, c.name) for c in AuditLog.__table__.c} for row in rows])
    assert PASSWORD not in rendered and secret not in rendered
    assert (
        result["access_token"] not in rendered
        and client.cookies.get(REFRESH_COOKIE) not in rendered
    )


@pytest.mark.parametrize("state", ["expired", "disabled", "auth_version"])
def test_server_session_state_revokes_access_and_refresh(auth_api, state):
    client, session, user_id, secret, clock = auth_api
    result = login(client, secret, clock).json()
    raw = client.cookies.get(REFRESH_COOKIE)
    if state == "expired":
        session.get(RefreshToken, token_hash(raw)).expires_at = clock[0] - timedelta(seconds=1)
    elif state == "disabled":
        session.get(User, user_id).status = "disabled"
    else:
        session.get(User, user_id).auth_version += 1
    session.commit()
    assert client.get("/api/v1/auth/me", headers=headers(result["access_token"])).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/refresh", headers={"X-CSRF-Token": result["csrf_token"]}
        ).status_code
        == 401
    )


def test_production_does_not_bypass_limits_when_redis_is_down(auth_api, monkeypatch):
    client, session, _, _, _ = auth_api
    monkeypatch.setattr(get_settings(), "app_env", "production")
    response = client.post("/api/v1/auth/login", json={"login": "auth", "password": PASSWORD})
    assert response.status_code == 503
    assert session.scalar(select(func.count(PartialAuth.token_id))) == 0


def test_password_rate_limit_returns_429_and_persists_failures(auth_api):
    client, session, user_id, _, _ = auth_api
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/login", json={"login": "auth", "password": "wrong-password"}
        )
        assert response.status_code == 401
    assert (
        client.post("/api/v1/auth/login", json={"login": "auth", "password": PASSWORD}).status_code
        == 429
    )
    session.expire_all()
    assert session.get(User, user_id).locked_until is not None
