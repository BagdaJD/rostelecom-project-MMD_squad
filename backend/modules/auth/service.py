"""Авторизация с 2FA: вход, промежуточное состояние, подтверждение TOTP, refresh."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    check_backup_code,
    decrypt_secret,
    encrypt_secret,
    hash_backup_codes,
    hash_password,
    issue_access_token,
    new_backup_codes,
    new_jti,
    new_totp_secret,
    verify_password,
    verify_totp,
)
from app.models import AuditLog, PartialAuth, RefreshToken, User
from app.schemas import LoginResponse, TokenPair


def _now() -> datetime:
    return datetime.now(timezone.utc)


def authenticate(session: Session, login: str, password: str, ip: str | None) -> LoginResponse:
    """Вход. При включённом 2FA выдаётся только partial-токен с коротким TTL."""
    user = session.scalar(select(User).where((User.login == login) | (User.email == login)))
    if user is None or user.status != "active":
        _audit(session, None, "login.unknown", ip)
        # Одинаковый ответ для «нет пользователя» и «неверный пароль» — без oracle.
        raise PermissionError("Неверные учётные данные")
    if user.locked_until and user.locked_until > _now():
        raise PermissionError("Учётная запись временно заблокирована")

    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1
        if user.failed_login_count >= 5:
            user.locked_until = _now() + timedelta(minutes=15)
            user.failed_login_count = 0
        _audit(session, user.id, "login.failed", ip)
        session.flush()
        raise PermissionError("Неверные учётные данные")

    user.failed_login_count = 0
    user.last_login_at = _now()

    if user.totp_enabled:
        partial = PartialAuth(
            token_id=new_jti(),
            user_id=user.id,
            expires_at=_now() + timedelta(minutes=get_settings().partial_auth_ttl_min),
        )
        session.add(partial)
        _audit(session, user.id, "login.mfa_pending", ip)
        return LoginResponse(mfa_required=True, partial_token=partial.token_id)

    _audit(session, user.id, "login.success", ip)
    pair = _issue_tokens(session, user, ip)
    return LoginResponse(mfa_required=False, access_token=pair.access_token, refresh_token=pair.refresh_token)


def confirm_2fa(session: Session, partial_token: str, code: str, ip: str | None) -> TokenPair:
    record = session.get(PartialAuth, partial_token)
    if record is None or record.expires_at < _now():
        raise PermissionError("Сессия подтверждения истекла, войдите заново")

    user = session.get(User, record.user_id)
    if user is None or not user.totp_secret_encrypted:
        raise PermissionError("Второй фактор не настроен")

    secret = decrypt_secret(user.totp_secret_encrypted)
    if verify_totp(secret, code):
        session.delete(record)
    elif check_backup_code(user.backup_codes_hash, code):
        # Резервный код одноразовый: расходуем, иначе он становится постоянным обходом.
        remaining = [c for c in (user.backup_codes_hash or "").split("|") if not _matches(c, code)]
        user.backup_codes_hash = "|".join(remaining) or None
        session.delete(record)
    else:
        _audit(session, user.id, "mfa.failed", ip)
        raise PermissionError("Неверный код подтверждения")

    _audit(session, user.id, "mfa.success", ip)
    return _issue_tokens(session, user, ip)


def _matches(stored_hash: str, code: str) -> bool:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    try:
        PasswordHasher().verify(stored_hash, code)
        return True
    except VerifyMismatchError:
        return False


def rotate_refresh(session: Session, jti: str, ip: str | None) -> TokenPair:
    token = session.get(RefreshToken, jti)
    if token is None or token.revoked_at or token.expires_at < _now():
        raise PermissionError("Refresh-токен недействителен")
    user = session.get(User, token.user_id)
    if user is None or user.status != "active":
        raise PermissionError("Учётная запись недоступна")
    token.revoked_at = _now()
    return _issue_tokens(session, user, ip)


def logout(session: Session, jti: str | None) -> None:
    if not jti:
        return
    token = session.get(RefreshToken, jti)
    if token and token.revoked_at is None:
        token.revoked_at = _now()


def enable_2fa(session: Session, user: User) -> tuple[str, list[str]]:
    """Возвращает secret для приложения-аутентификатора и резервные коды (один раз)."""
    secret = new_totp_secret()
    codes = new_backup_codes()
    user.totp_secret_encrypted = encrypt_secret(secret)
    user.totp_enabled = True
    user.backup_codes_hash = hash_backup_codes(codes)
    _audit(session, user.id, "mfa.enabled", None)
    return secret, codes


def disable_2fa(session: Session, user: User) -> None:
    user.totp_enabled = False
    user.totp_secret_encrypted = None
    user.backup_codes_hash = None
    _audit(session, user.id, "mfa.disabled", None)


def create_user(session: Session, email: str, login: str, password: str, role: str) -> User:
    user = User(email=email, login=login, password_hash=hash_password(password), role=role)
    session.add(user)
    session.flush()
    return user


def _issue_tokens(session: Session, user: User, ip: str | None) -> TokenPair:
    access = issue_access_token(user.id, user.role)
    jti = new_jti()
    session.add(
        RefreshToken(
            jti=jti,
            user_id=user.id,
            expires_at=_now() + timedelta(days=get_settings().refresh_token_ttl_days),
            ip=ip,
        )
    )
    return TokenPair(access_token=access, refresh_token=jti)


def _audit(session: Session, user_id: int | None, action: str, ip: str | None) -> None:
    """Логи событий входа и выгрузок; без паролей и кодов (ТЗ 13)."""
    session.add(AuditLog(user_id=user_id, action=action, ip=ip))
