"""MFA enrollment and browser sessions; refresh secrets never enter JSON or URLs."""

import hmac

import pyotp
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.deps import CurrentUser, DbSession
from app.core.ratelimit import client_key, is_limited, reset
from app.schemas import LoginRequest, LoginResponse, Setup2FARequest, TokenPair, Verify2FARequest
from modules.auth import service as auth

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE = "rtk_refresh"
CSRF_COOKIE = "rtk_csrf"


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _origin(request: Request) -> None:
    origin = request.headers.get("origin")
    current = f"{request.url.scheme}://{request.url.netloc}"
    if (
        request.headers.get("sec-fetch-site") == "cross-site"
        or origin is not None
        and origin not in (*get_settings().cors_origins, current)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Источник запроса не разрешён")


def _csrf(request: Request) -> str:
    _origin(request)
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get("x-csrf-token", "")
    if (
        not cookie
        or not header
        or len(header) > 128
        or not hmac.compare_digest(cookie.encode(), header.encode())
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Требуется корректный X-CSRF-Token")
    return header


def _cookies(response: Response, tokens: auth.IssuedTokens) -> None:
    settings = get_settings()
    age = max(int((tokens.expires_at - auth._now()).total_seconds()), 0)
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=age,
        path=f"{settings.api_prefix}/auth",
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
    )
    response.set_cookie(
        CSRF_COOKIE,
        tokens.csrf_token,
        max_age=age,
        path="/",
        secure=settings.secure_cookies,
        samesite="strict",
    )


def _clear_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        REFRESH_COOKIE,
        path=f"{settings.api_prefix}/auth",
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
    )
    response.delete_cookie(CSRF_COOKIE, path="/", secure=settings.secure_cookies, samesite="strict")


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, session: DbSession) -> LoginResponse:
    _origin(request)
    key = client_key("login", payload.login, _ip(request))
    if is_limited(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много попыток входа")
    try:
        result = auth.authenticate(session, payload.login, payload.password, _ip(request))
    except PermissionError as exc:
        session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    reset(key)
    session.commit()
    return result


@router.post("/2fa/setup")
def setup_2fa(payload: Setup2FARequest, request: Request, session: DbSession) -> dict:
    _origin(request)
    try:
        secret, email = auth.setup_2fa(session, payload.partial_token, _ip(request))
    except PermissionError as exc:
        session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    session.commit()
    return {
        "secret": secret,
        "otpauth_hint": pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="RTK"),
    }


@router.post("/2fa/verify", response_model=TokenPair)
def verify_2fa(
    payload: Verify2FARequest, request: Request, response: Response, session: DbSession
) -> TokenPair:
    _origin(request)
    key = client_key("2fa", payload.partial_token, _ip(request))
    if is_limited(key, limit=10):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много попыток подтверждения"
        )
    try:
        tokens = auth.confirm_2fa(session, payload.partial_token, payload.code, _ip(request))
    except PermissionError as exc:
        session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    reset(key)
    session.commit()
    _cookies(response, tokens)
    return tokens.public()


@router.post("/2fa/disable")
def disable_2fa(user: CurrentUser) -> dict:
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        "Второй фактор обязателен; восстановление выполняется администратором",
    )


@router.post("/refresh", response_model=TokenPair)
def refresh(request: Request, response: Response, session: DbSession) -> TokenPair | JSONResponse:
    csrf = _csrf(request)
    raw = request.cookies.get(REFRESH_COOKIE)
    try:
        if not raw:
            raise PermissionError("Требуется сессия")
        tokens = auth.rotate_refresh(session, raw, csrf, _ip(request))
    except PermissionError as exc:
        session.commit()
        rejected = JSONResponse(status_code=401, content={"detail": str(exc)})
        _clear_cookies(rejected)
        return rejected
    session.commit()
    _cookies(response, tokens)
    return tokens.public()


@router.post("/logout")
def logout(request: Request, response: Response, session: DbSession) -> dict:
    _origin(request)
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        csrf = _csrf(request)
        try:
            auth.logout(session, raw, csrf, _ip(request))
        except PermissionError:
            pass
    session.commit()
    _clear_cookies(response)
    return {"status": "ok"}


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return {"id": user.id, "login": user.login, "role": user.role, "mfa_enabled": user.totp_enabled}
