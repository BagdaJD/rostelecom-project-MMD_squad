"""Only the worker/seed trains. HTTP loads a signed artifact or uses the documented fallback."""

import hashlib
import hmac
import json
import pickle
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.persistence import insert
from app.models import ModelArtifact

KEY = "win-model-v1"
_cache = {}


def fingerprint(deals, regions):
    state = {
        "version": KEY,
        "deals": [
            {c.name: getattr(d, c.name) for c in d.__table__.c}
            for d in sorted(deals, key=lambda d: d.id)
        ],
        "regions": [
            {c.name: getattr(r, c.name) for c in r.__table__.c}
            for r in sorted(regions.by_id.values(), key=lambda r: r.id)
        ],
    }
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()


def signature(payload, digest):
    return hmac.new(
        get_settings().secret_key.encode(), digest.encode() + payload, hashlib.sha256
    ).hexdigest()


def prepare(session):
    from modules.deal_calculator import service

    deals, regions = service._deals(session), service.Regions(session)
    digest = fingerprint(deals, regions)
    existing = session.get(ModelArtifact, KEY)
    if (
        existing
        and existing.fingerprint == digest
        and hmac.compare_digest(existing.signature, signature(existing.payload, digest))
    ):
        return False
    service._WIN_MODEL_CACHE.clear()
    model = service.win_model(deals, regions)
    payload = pickle.dumps(model, protocol=5)
    statement = insert(session, ModelArtifact).values(
        key=KEY,
        fingerprint=digest,
        payload=payload,
        signature=signature(payload, digest),
        trained_at=datetime.now(UTC),
    )
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["key"],
            set_={
                "fingerprint": digest,
                "payload": payload,
                "signature": signature(payload, digest),
                "trained_at": datetime.now(UTC),
            },
        )
    )
    return True


def load(session, deals, regions):
    digest = fingerprint(deals, regions)
    row = session.get(ModelArtifact, KEY)
    if (
        row is None
        or row.fingerprint != digest
        or not hmac.compare_digest(row.signature, signature(row.payload, digest))
    ):
        return None
    if digest not in _cache:
        _cache.clear()
        _cache[digest] = pickle.loads(row.payload)
    return _cache[digest]
