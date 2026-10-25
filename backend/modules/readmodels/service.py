"""Prepared JSON projections, published atomically through PostgreSQL materialized views."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, text

from app.core.persistence import insert
from app.models import DataRevision, ReadModelSnapshot

VIEWS = {
    "radar": "mv_region_density",
    "white": "mv_white_space",
    "timeline": "mv_investment_timeline",
}
VERSION = "readmodels-0.1"


def mark_changed(session):
    statement = insert(session, DataRevision).values(id=1, revision=1)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["id"], set_={"revision": DataRevision.revision + 1}
        )
    )


def revision(session):
    return session.scalar(select(DataRevision.revision).where(DataRevision.id == 1)) or 0


def snapshot_key(kind, level):
    return f"{kind}:{date.today().isoformat()}:{level}"


def get_snapshot(session, kind, level):
    key = snapshot_key(kind, level)
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    current = revision(session)
    if session.get_bind().dialect.name == "postgresql":
        return session.scalar(
            text(
                f"SELECT payload FROM {VIEWS[kind]} WHERE snapshot_key=:key "
                "AND source_revision=:revision AND calculated_at>=:cutoff AND version=:version"
            ),
            {"key": key, "revision": current, "cutoff": cutoff, "version": VERSION},
        )
    return session.scalar(
        select(ReadModelSnapshot.payload).where(
            ReadModelSnapshot.key == key,
            ReadModelSnapshot.source_revision == current,
            ReadModelSnapshot.calculated_at >= cutoff,
            ReadModelSnapshot.version == VERSION,
        )
    )


def rebuild(session):
    from modules.investments.service import timeline
    from modules.radar.service import heatmap, white_spaces

    source_revision = revision(session)
    entries = {}
    for level in ("region", "municipality"):
        entries[snapshot_key("radar", level)] = [
            c.model_dump(mode="json") for c in heatmap(session, level=level, _bypass_cache=True)
        ]
        entries[snapshot_key("white", level)] = [
            c.model_dump(mode="json")
            for c in white_spaces(session, level=level, _bypass_cache=True)
        ]
    for period in ("month", "quarter", "year"):
        entries[snapshot_key("timeline", period)] = [
            c.model_dump(mode="json") for c in timeline(session, period=period, _bypass_cache=True)
        ]
    if revision(session) != source_revision:
        raise RuntimeError("Source changed while preparing read models; retry")
    now = datetime.now(UTC)
    for key, payload in entries.items():
        statement = insert(session, ReadModelSnapshot).values(
            key=key,
            payload=payload,
            source_revision=source_revision,
            calculated_at=now,
            version=VERSION,
        )
        session.execute(
            statement.on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "payload": statement.excluded.payload,
                    "source_revision": source_revision,
                    "calculated_at": now,
                    "version": VERSION,
                },
            )
        )
    session.flush()
    if session.get_bind().dialect.name == "postgresql":
        for view in VIEWS.values():
            session.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}"))
    return len(entries)
