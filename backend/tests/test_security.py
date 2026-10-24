"""Безопасность: пароли, TOTP, токены, шифрование секрета."""

from __future__ import annotations

import pyotp
import pytest

from app.core.security import (
    check_backup_code,
    decode_token,
    decrypt_secret,
    encrypt_secret,
    hash_backup_codes,
    hash_password,
    issue_access_token,
    new_backup_codes,
    new_totp_secret,
    verify_password,
    verify_totp,
)


def test_password_hash_is_not_reversible():
    hashed = hash_password("s3cret-passphrase")
    assert hashed != "s3cret-passphrase"
    assert verify_password(hashed, "s3cret-passphrase")
    assert not verify_password(hashed, "wrong")


def test_totp_roundtrip():
    secret = new_totp_secret()
    code = pyotp.TOTP(secret).now()
    assert verify_totp(secret, code)
    assert not verify_totp(secret, "000000" if code != "000000" else "111111")


def test_totp_secret_is_encrypted_at_rest():
    secret = new_totp_secret()
    stored = encrypt_secret(secret)
    assert secret not in stored
    assert decrypt_secret(stored) == secret


def test_backup_codes_are_hashed_and_single_use_lookup():
    codes = new_backup_codes(4)
    stored = hash_backup_codes(codes)
    for code in codes:
        assert code not in stored, "резервные коды хранятся только в виде хеша"
        assert check_backup_code(stored, code)
    assert not check_backup_code(stored, "ZZZZZZZZ")


def test_access_token_scopes():
    token = issue_access_token(7, "analyst")
    payload = decode_token(token)
    assert payload["sub"] == "7"
    assert payload["role"] == "analyst"
    assert payload["scope"] == "full"

    partial = decode_token(issue_access_token(7, "analyst", scope="mfa_pending"))
    assert partial["scope"] == "mfa_pending"


def test_invalid_token_rejected():
    import jwt

    with pytest.raises(jwt.PyJWTError):
        decode_token("not-a-token")
