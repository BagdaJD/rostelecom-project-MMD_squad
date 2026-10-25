"""Пароли, токены, TOTP и шифрование секрета 2FA (ТЗ 13)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

_ph = PasswordHasher()

ROLES = ("admin", "analyst", "manager")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _fernet() -> Fernet:
    """Ключ Fernet из любой строки окружения: детерминированная производная 32 байта."""
    digest = hashlib.sha256(get_settings().totp_encryption_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("TOTP_ENCRYPTION_KEY не соответствует ключу шифрования") from exc


def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=valid_window)


def totp_counter(secret: str, code: str, at: datetime) -> int | None:
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    counter = totp.timecode(at)
    for offset in (0, -1, 1):
        candidate = counter + offset
        if candidate >= 0 and hmac.compare_digest(totp.generate_otp(candidate), code):
            return candidate
    return None


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_backup_codes(codes: list[str]) -> str:
    return "|".join(hash_password(c) for c in codes)


def check_backup_code(codes_hash: str | None, code: str) -> bool:
    if not codes_hash:
        return False
    for stored in codes_hash.split("|"):
        try:
            if _ph.verify(stored, code):
                return True
        except (VerificationError, InvalidHashError):
            continue
    return False


def issue_access_token(
    user_id: int,
    role: str,
    scope: str = "full",
    *,
    session_id: str | None = None,
    auth_version: int = 0,
    mfa_method: str | None = None,
) -> str:
    now = datetime.now(UTC)
    ttl = (
        get_settings().partial_auth_ttl_min
        if scope == "mfa_pending"
        else get_settings().access_token_ttl_min
    )
    payload = {
        "sub": str(user_id),
        "role": role,
        "scope": scope,
        "iat": now,
        "exp": now + timedelta(minutes=ttl),
        "jti": str(uuid.uuid4()),
        "sid": session_id,
        "v": auth_version,
        "amr": ["pwd", mfa_method] if mfa_method else ["pwd"],
    }
    return jwt.encode(payload, get_settings().secret_key, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(
        token,
        get_settings().secret_key,
        algorithms=["HS256"],
        options={"require": ["sub", "exp", "iat", "jti", "scope"]},
    )


def new_jti() -> str:
    return str(uuid.uuid4())


def new_backup_codes(count: int = 8) -> list[str]:
    return [secrets.token_hex(4).upper() for _ in range(count)]
