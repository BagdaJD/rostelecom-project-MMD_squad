"""Фоновые задачи: загрузка источников, пересчёт скоринга, уведомления, витрины."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

log = logging.getLogger("worker.jobs")


def run_ingestion(settings=None) -> dict:
    """Плановая загрузка. Адаптеры выключены, пока не согласованы условия использования."""
    from ingestion.sources import get_source

    if settings is not None and not settings.ingest_enabled:
        log.info("ingestion отключён (INGEST_ENABLED=false)")
        return {"enabled": False}

    from ingestion.loader import load_bundle
    from app.db.session import SessionLocal

    stats: dict[str, int] = {}
    with SessionLocal() as session:
        for name in ("demo",):
            source = get_source(name)
            if source is None:
                continue
            bundle = source.fetch()
            result = load_bundle(session, bundle)
            stats[name] = result.companies
        session.commit()
    log.info("ingestion done: %s", stats)
    return stats


def refresh_scoring() -> int:
    """Скоринг пересчитывается отдельно от HTTP-запроса; результат — в scoring_snapshot."""
    from app.core.config import get_settings
    from app.db.session import SessionLocal
    from app.models import Company, Region, ScoringSnapshot
    from modules.investments import service as investments
    from modules.radar import service as radar

    settings = get_settings()
    written = 0
    with SessionLocal() as session:
        cells = radar.heatmap(
            session,
            active_projects=investments.active_projects_by_slice(session),
            open_tenders=investments.open_tenders_by_slice(session),
        )
        for cell in cells:
            session.add(
                ScoringSnapshot(
                    subject_type="region",
                    subject_id=cell.region_id,
                    score=cell.potential_score,
                    factors_json=[{"code": "potential_score", "label": "Потенциал",
                                   "contribution": cell.potential_score},
                                  {"code": "presence_score", "label": "Присутствие",
                                   "contribution": cell.presence_score}],
                    scoring_mode=settings.scoring_mode,
                    model_version=settings.model_version,
                )
            )
            written += 1
        session.commit()
    log.info("scoring refreshed: %s срезов", written)
    return written


def dispatch_notifications() -> int:
    """Новые проекты и тендеры → уведомления подписчикам."""
    from app.db.session import SessionLocal
    from app.models import InvestmentProject, Tender
    from modules.investments import service as investments
    from modules.notifications import service as notifications

    created = 0
    with SessionLocal() as session:
        projects = list(session.scalars(
            select(InvestmentProject).order_by(InvestmentProject.id.desc()).limit(50)
        ))
        tenders = list(session.scalars(
            select(Tender).order_by(Tender.id.desc()).limit(50)
        ))
        created += notifications.notify_new_projects(session, projects)
        created += notifications.notify_new_tenders(session, tenders)
        session.commit()
    if created:
        log.info("уведомлений создано: %s", created)
    return created


def rebuild_matviews() -> None:
    """Витрины для карты и таймлайна. Конкретные MV добавляются вместе с миграциями."""
    log.info("пересчёт витрин запланирован: mv_region_density, mv_white_space, mv_investment_timeline")


def heartbeat() -> str:
    return datetime.now(timezone.utc).isoformat()
