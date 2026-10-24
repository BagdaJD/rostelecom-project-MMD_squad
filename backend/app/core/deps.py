"""Зависимости FastAPI: текущий пользователь и проверка роли на сервере."""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_session
from app.models import User

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

    # Токен промежуточного состояния не даёт доступа к закрытым маршрутам.
    if payload.get("scope") != "full":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Не подтверждён второй фактор")

    user = session.get(User, int(payload["sub"]))
    if user is None or user.status != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Учётная запись недоступна")
    return user


def require_roles(*roles: str):
    def dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        return user

    return dependency


CurrentUser = Annotated[User, Depends(get_current_user)]
AnalystOrAdmin = Annotated[User, Depends(require_roles("admin", "analyst"))]
