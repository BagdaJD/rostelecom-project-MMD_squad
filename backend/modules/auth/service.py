"""Password challenges, mandatory MFA and one-use, revocable browser sessions."""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    ROLES,
    decrypt_secret,
    encrypt_secret,
    hash_backup_codes,
    hash_password,
    issue_access_token,
    new_backup_codes,
    new_jti,
    new_totp_secret,
    token_hash,
    totp_counter,
    verify_password,
)
from app.models import AuditLog, PartialAuth, RefreshToken, User
from app.schemas import LoginResponse, TokenPair

MAX_MFA_ATTEMPTS = 5


def _now() -> datetime:
    return datetime.now(UTC)


def utc(value: datetime) -> datetime:

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass
class IssuedTokens:
    access_token: str
    refresh_token: str
    csrf_token: str
    expires_at: datetime
    backup_codes: list[str] | None = None

    def public(self) -> TokenPair:
        return TokenPair(
            access_token=self.access_token,
            csrf_token=self.csrf_token,
            expires_in=get_settings().access_token_ttl_min * 60,
            backup_codes=self.backup_codes,
        )


def authenticate(session: Session, login: str, password: str, ip: str | None) -> LoginResponse:
    user = session.scalar(
        select(User).where((User.login == login) | (User.email == login)).with_for_update()
    )
    if user is None or user.status != "active" or user.role not in ROLES:
        _audit(session, None, "login.failed", ip)
        raise PermissionError("Неверные учётные данные")
    if user.locked_until and utc(user.locked_until) > _now():
        _audit(session, user.id, "login.locked", ip)
        raise PermissionError("Учётная запись временно заблокирована")
    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1
        if user.failed_login_count >= get_settings().rate_limit_login:
            user.locked_until = _now() + timedelta(seconds=get_settings().rate_limit_window_sec)
            user.failed_login_count = 0
        _audit(session, user.id, "login.failed", ip)
        session.flush()
        raise PermissionError("Неверные учётные данные")
    user.locked_until = None
    configured = bool(user.totp_enabled and user.totp_secret_encrypted)
    partial = PartialAuth(
        token_id=new_jti(),
        user_id=user.id,
        auth_version=user.auth_version,
        scope="mfa_pending" if configured else "mfa_enroll",
        expires_at=_now() + timedelta(minutes=get_settings().partial_auth_ttl_min),
    )
    session.add(partial)
    _audit(session, user.id, "login.mfa_pending", ip)
    return LoginResponse(
        mfa_required=True, partial_token=partial.token_id, mfa_setup_required=not configured
    )


def _challenge(session: Session, partial_token: str) -> tuple[PartialAuth, User]:
    record = session.get(PartialAuth, partial_token)
    if record is None or utc(record.expires_at) <= _now():
        raise PermissionError("Сессия подтверждения истекла, войдите заново")
    user = session.scalar(
        select(User)
        .where(User.id == record.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        user is None
        or user.status != "active"
        or user.role not in ROLES
        or user.auth_version != record.auth_version
        or record.failed_attempts >= MAX_MFA_ATTEMPTS
        or record.scope not in ("mfa_pending", "mfa_enroll")
    ):
        raise PermissionError("Сессия подтверждения недействительна, войдите заново")
    if user.locked_until and utc(user.locked_until) > _now():
        raise PermissionError("Учётная запись временно заблокирована")
    return record, user


def setup_2fa(session: Session, partial_token: str, ip: str | None) -> tuple[str, str]:
    record, user = _challenge(session, partial_token)
    if record.scope != "mfa_enroll" or user.totp_enabled:
        raise PermissionError("Для этого входа настройка второго фактора не разрешена")
    if record.secret_encrypted:
        raise ValueError("Секрет уже выдан; при его утрате войдите заново")
    secret = new_totp_secret()
    record.secret_encrypted = encrypt_secret(secret)
    _audit(session, user.id, "mfa.setup_started", ip)
    session.flush()
    return secret, user.email


def _failed_mfa(session: Session, record: PartialAuth, ip: str | None) -> None:

    failures = session.scalar(
        update(User)
        .where(User.id == record.user_id)
        .values(failed_login_count=User.failed_login_count + 1)
        .returning(User.failed_login_count)
    )
    if failures is not None and failures >= get_settings().rate_limit_login:
        session.execute(
            update(User)
            .where(User.id == record.user_id)
            .values(
                failed_login_count=0,
                locked_until=_now() + timedelta(seconds=get_settings().rate_limit_window_sec),
            )
        )
    attempts = session.scalar(
        update(PartialAuth)
        .where(PartialAuth.token_id == record.token_id)
        .values(failed_attempts=PartialAuth.failed_attempts + 1)
        .returning(PartialAuth.failed_attempts)
    )
    if attempts is not None and attempts >= MAX_MFA_ATTEMPTS:
        session.execute(delete(PartialAuth).where(PartialAuth.token_id == record.token_id))
    _audit(session, record.user_id, "mfa.failed", ip)
    raise PermissionError("Неверный или уже использованный код подтверждения")


def confirm_2fa(session: Session, partial_token: str, code: str, ip: str | None) -> IssuedTokens:
    record, user = _challenge(session, partial_token)
    enrolling = record.scope == "mfa_enroll"
    encrypted = record.secret_encrypted if enrolling else user.totp_secret_encrypted
    if (
        not encrypted
        or (not enrolling and not user.totp_enabled)
        or (enrolling and user.totp_enabled)
    ):
        raise PermissionError("Второй фактор не настроен для этой сессии")
    secret = decrypt_secret(encrypted)
    counter = totp_counter(secret, code, _now())
    hashes = user.backup_codes_hash or ""
    matched = None
    if counter is None and not enrolling and len(code) == 8:
        matched = next(
            (
                stored
                for stored in hashes.split("|")
                if stored and verify_password(stored, code.upper())
            ),
            None,
        )
    if counter is not None and not enrolling and user.totp_last_counter is not None:
        if counter <= user.totp_last_counter:
            _failed_mfa(session, record, ip)
    if counter is None and matched is None:
        _failed_mfa(session, record, ip)

    consumed = session.execute(
        delete(PartialAuth)
        .where(
            PartialAuth.token_id == record.token_id,
            PartialAuth.auth_version == user.auth_version,
            PartialAuth.expires_at > _now(),
            PartialAuth.failed_attempts < MAX_MFA_ATTEMPTS,
        )
        .execution_options(synchronize_session="fetch")
    ).rowcount
    if consumed != 1:
        raise PermissionError("Сессия подтверждения уже использована")
    method = "otp" if counter is not None else "recovery"
    if matched is not None:
        remaining = "|".join(stored for stored in hashes.split("|") if stored != matched) or None
        consumed_code = session.execute(
            update(User)
            .where(
                User.id == user.id,
                User.backup_codes_hash == hashes,
                User.auth_version == record.auth_version,
            )
            .values(backup_codes_hash=remaining)
        ).rowcount
        if consumed_code != 1:
            raise PermissionError("Резервный код уже использован")
    elif not enrolling:
        claimed = session.execute(
            update(User)
            .where(
                User.id == user.id,
                User.auth_version == record.auth_version,
                or_(User.totp_last_counter.is_(None), User.totp_last_counter < counter),
            )
            .values(totp_last_counter=counter)
        ).rowcount
        if claimed != 1:
            raise PermissionError("Код подтверждения уже использован")
    backup_codes = None
    if enrolling:
        _invalidate_sessions(session, user)
        user.totp_secret_encrypted = encrypted
        user.totp_enabled = True
        user.totp_last_counter = counter
        backup_codes = new_backup_codes()
        user.backup_codes_hash = hash_backup_codes(backup_codes)
        _audit(session, user.id, "mfa.enabled", ip)
    user.last_login_at = _now()
    user.failed_login_count = 0
    user.locked_until = None
    session.flush()
    _audit(session, user.id, "mfa.success", ip)
    tokens = _issue_tokens(session, user, ip, method=method)
    tokens.backup_codes = backup_codes
    return tokens


def _issue_tokens(
    session: Session,
    user: User,
    ip: str | None,
    *,
    method: str = "otp",
    expires_at: datetime | None = None,
    family_id: str | None = None,
) -> IssuedTokens:
    if not user.totp_enabled or not user.totp_secret_encrypted:
        raise PermissionError("Требуется подтверждение второго фактора")
    raw = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    identifier = token_hash(raw)
    expiry = (
        utc(expires_at)
        if expires_at
        else (_now() + timedelta(days=get_settings().refresh_token_ttl_days))
    )
    session.add(
        RefreshToken(
            jti=identifier,
            user_id=user.id,
            auth_version=user.auth_version,
            expires_at=expiry,
            csrf_hash=token_hash(csrf),
            family_id=family_id or new_jti(),
            ip=ip,
        )
    )
    access = issue_access_token(
        user.id, user.role, session_id=identifier, auth_version=user.auth_version, mfa_method=method
    )
    session.flush()
    return IssuedTokens(access, raw, csrf, expiry)


def _refresh_record(session: Session, raw: str, csrf: str) -> RefreshToken:
    if not 32 <= len(raw) <= 128:
        raise PermissionError("Сессия недействительна")
    token = session.get(RefreshToken, token_hash(raw))
    if (
        token is None
        or not token.csrf_hash
        or not hmac.compare_digest(token.csrf_hash, token_hash(csrf))
    ):
        raise PermissionError("Сессия недействительна")
    return token


def rotate_refresh(session: Session, raw: str, csrf: str, ip: str | None) -> IssuedTokens:
    token = _refresh_record(session, raw, csrf)
    user = session.scalar(
        select(User)
        .where(User.id == token.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        token.revoked_at
        or utc(token.expires_at) <= _now()
        or user is None
        or user.status != "active"
        or user.role not in ROLES
        or not user.totp_enabled
        or token.auth_version != user.auth_version
    ):
        _audit(session, token.user_id, "refresh.rejected", ip)
        raise PermissionError("Сессия истекла или отозвана")
    claimed = session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.jti == token.jti,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > _now(),
        )
        .values(revoked_at=_now())
        .execution_options(synchronize_session="fetch")
    ).rowcount
    if claimed != 1:
        raise PermissionError("Сессия уже обновлена")
    _audit(session, user.id, "refresh.success", ip)
    return _issue_tokens(
        session, user, ip, method="mfa", expires_at=token.expires_at, family_id=token.family_id
    )


def logout(session: Session, raw: str | None, csrf: str, ip: str | None) -> None:
    if raw is None:
        return
    token = _refresh_record(session, raw, csrf)
    session.scalar(select(User).where(User.id == token.user_id).with_for_update())

    family = (
        RefreshToken.family_id == token.family_id
        if token.family_id
        else (RefreshToken.jti == token.jti)
    )
    session.execute(
        update(RefreshToken)
        .where(family, RefreshToken.user_id == token.user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    _audit(session, token.user_id, "logout", ip)


def _invalidate_sessions(session: Session, user: User) -> None:
    version = session.scalar(select(User.auth_version).where(User.id == user.id).with_for_update())
    user.auth_version = version + 1
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    session.execute(delete(PartialAuth).where(PartialAuth.user_id == user.id))
    session.flush()


def enable_2fa(session: Session, user: User) -> tuple[str, list[str]]:
    """Trusted CLI provisioning/recovery; invalidates every previous session."""
    _invalidate_sessions(session, user)
    secret, codes = new_totp_secret(), new_backup_codes()
    user.totp_secret_encrypted = encrypt_secret(secret)
    user.totp_enabled = True
    user.totp_last_counter = None
    user.backup_codes_hash = hash_backup_codes(codes)
    _audit(session, user.id, "mfa.provisioned", None)
    return secret, codes


def disable_2fa(session: Session, user: User) -> None:
    """Administrative recovery only: access stays blocked until MFA is re-enrolled."""
    _invalidate_sessions(session, user)
    user.totp_enabled = False
    user.totp_secret_encrypted = None
    user.totp_last_counter = None
    user.backup_codes_hash = None
    _audit(session, user.id, "mfa.reset", None)


def create_user(session: Session, email: str, login: str, password: str, role: str) -> User:
    if role not in ROLES or len(password) < 8:
        raise ValueError("Некорректная роль или пароль короче 8 символов")
    user = User(email=email, login=login, password_hash=hash_password(password), role=role)
    session.add(user)
    session.flush()
    return user


def _audit(session: Session, user_id: int | None, action: str, ip: str | None) -> None:
    session.add(AuditLog(user_id=user_id, action=action, ip=ip))
