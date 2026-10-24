from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import CurrentUser, DbSession, get_current_user
from app.core.ratelimit import client_key, is_limited, reset
from app.schemas import LoginRequest, LoginResponse, TokenPair, Verify2FARequest
from modules.auth import service as auth

router = APIRouter(prefix="/auth", tags=["auth"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, session: DbSession) -> LoginResponse:
    key = client_key("login", payload.login, _ip(request))
    if is_limited(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много попыток входа")
    try:
        result = auth.authenticate(session, payload.login, payload.password, _ip(request))
    except PermissionError as exc:
        session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    session.commit()
    if not result.mfa_required:
        reset(key)
    return result


@router.post("/2fa/verify", response_model=TokenPair)
def verify_2fa(payload: Verify2FARequest, request: Request, session: DbSession) -> TokenPair:
    # Отдельный лимит: без него шестизначный TOTP перебирается за минуты.
    key = client_key("2fa", payload.partial_token, _ip(request))
    if is_limited(key, limit=10):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много попыток подтверждения")
    try:
        tokens = auth.confirm_2fa(session, payload.partial_token, payload.code, _ip(request))
    except PermissionError as exc:
        session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    session.commit()
    reset(key)
    return tokens


@router.post("/2fa/setup")
def setup_2fa(session: DbSession, user: CurrentUser) -> dict:
    secret, codes = auth.enable_2fa(session, user)
    session.commit()
    # secret показывается один раз — пользователь должен внести его в приложение.
    return {"secret": secret, "backup_codes": codes,
            "otpauth_hint": f"otpauth://totp/RTK?secret={secret}&issuer=RTK"}


@router.post("/2fa/disable")
def disable_2fa(session: DbSession, user: CurrentUser) -> dict:
    auth.disable_2fa(session, user)
    session.commit()
    return {"status": "disabled"}


@router.post("/refresh", response_model=TokenPair)
def refresh(refresh_token: str, request: Request, session: DbSession) -> TokenPair:
    try:
        tokens = auth.rotate_refresh(session, refresh_token, _ip(request))
    except PermissionError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    session.commit()
    return tokens


@router.post("/logout")
def logout(session: DbSession, refresh_token: str | None = None) -> dict:
    auth.logout(session, refresh_token)
    session.commit()
    return {"status": "ok"}


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return {"id": user.id, "login": user.login, "role": user.role, "mfa_enabled": user.totp_enabled}
