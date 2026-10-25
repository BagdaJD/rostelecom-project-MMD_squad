"""Hash before/after states; credentials and raw input never enter audit payloads."""

import hashlib
import json

from sqlalchemy.orm import Session

from app.models import AuditLog


def _digest(state: dict | None) -> str | None:
    if state is None:
        return None
    raw = json.dumps(state, sort_keys=True, ensure_ascii=False, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def record(
    session: Session,
    user_id: int | None,
    action: str,
    object_type: str,
    object_id: int,
    *,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            object_type=object_type,
            object_id=str(object_id),
            before_hash=_digest(before),
            after_hash=_digest(after),
        )
    )
