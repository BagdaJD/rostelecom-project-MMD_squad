"""Background ingestion, notifications, prepared read models and durable exports."""

import logging
from datetime import UTC, datetime

log = logging.getLogger("worker.jobs")


def run_ingestion(settings=None):
    from app.core.config import get_settings
    from app.db.session import SessionLocal

    settings = settings or get_settings()
    if not settings.ingest_enabled:
        return {"enabled": False}
    with SessionLocal() as session:
        if settings.data_mode == "case":
            from ingestion.case_workbook import import_case

            result = {"case": import_case(session, settings.case_workbook_path)}
        else:
            from ingestion.loader import load_bundle, read_bundle

            result = load_bundle(session, read_bundle(settings.demo_bundle_path)).as_dict()
        session.commit()
    rebuild_matviews()
    refresh_models()
    return result


def refresh_scoring():

    return rebuild_matviews()


def dispatch_notifications():
    from app.db.session import SessionLocal
    from modules.notifications.service import dispatch

    with SessionLocal() as session:
        count = dispatch(session)
        session.commit()
    return count


def rebuild_matviews():
    from app.db.session import SessionLocal
    from modules.readmodels.service import rebuild

    with SessionLocal() as session:
        count = rebuild(session)
        session.commit()
    return count


def refresh_models():
    from app.db.session import SessionLocal
    from modules.deal_calculator.artifacts import prepare

    with SessionLocal() as session:
        changed = prepare(session)
        session.commit()
    return changed


def dispatch_export_tasks():
    from modules.exports.tasks import dispatch

    return dispatch()


def heartbeat():
    return datetime.now(UTC).isoformat()
