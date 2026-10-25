"""Зависимости FastAPI: текущий пользователь и проверка роли на сервере."""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import ROLES, decode_token
from app.db.session import get_session
from app.models import RefreshToken, User
from modules.auth import service as auth

_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_session)]


def get_current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется аутентификация")
    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Токен недействителен") from exc

    if payload.get("scope") != "full":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Не подтверждён второй фактор")

    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError, KeyError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Токен недействителен") from exc
    user = session.get(User, user_id)
    if user is None or user.status != "active" or user.role not in ROLES:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Учётная запись недоступна")
    if not user.totp_enabled or not user.totp_secret_encrypted:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Требуется настройка второго фактора")
    amr, sid = payload.get("amr"), payload.get("sid")
    if (
        not isinstance(amr, list)
        or "pwd" not in amr
        or not any(method in amr for method in ("otp", "recovery", "mfa"))
        or not isinstance(sid, str)
        or len(sid) != 64
        or type(payload.get("v")) is not int
        or payload["v"] != user.auth_version
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия недействительна")
    token = session.get(RefreshToken, sid)
    if (
        token is None
        or token.user_id != user.id
        or token.revoked_at is not None
        or token.auth_version != user.auth_version
        or auth.utc(token.expires_at) <= auth._now()
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия истекла или отозвана")
    return user


def require_roles(*roles: str):
    def dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        return user

    return dependency


CurrentUser = Annotated[User, Depends(get_current_user)]
AnalystOrAdmin = Annotated[User, Depends(require_roles("admin", "analyst"))]
ManagerOrAdmin = Annotated[User, Depends(require_roles("admin", "manager"))]
AdminUser = Annotated[User, Depends(require_roles("admin"))]
