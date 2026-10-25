"""Таблицы и данные калькулятора: ``python -m modules.deal_calculator.seed`` (из папки backend).

* использует схему после ``alembic upgrade head``;
* загружает бандл кейса: регионы и коэффициенты (МОД3_Таб1), уровни (Таб2), этапы работ
  (Таб3), каталог (Таб4) и демо-историю сделок. Повторный запуск обновляет справочники
  и не дублирует сделки.

Ключи::

    --bundle PATH   другой бандл (например, реальные контракты, см. docs/calculator.md)
    --create-all    старый обход миграций, оставлен для совместимости демо
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.deal_calculator.models import (
    CALC_TABLES,
    CalcDeal,
    CalcDictionary,
    CalcPosition,
    CalcRegion,
)

DEFAULT_BUNDLE = Path(__file__).resolve().parent / "data" / "case_bundle.json"
DICTIONARIES = ("project_level", "work_stage", "payment_scheme")


def create_tables(bind, everything: bool = False) -> None:
    from app.db.base import Base

    if everything:
        from app.models import Base as ApplicationBase

        ApplicationBase.metadata.create_all(bind)
    else:
        from app.models import ModelArtifact

        Base.metadata.create_all(bind, tables=[*CALC_TABLES, ModelArtifact.__table__])


def _fingerprint(row: dict) -> str:
    key = json.dumps(
        {
            k: row.get(k)
            for k in (
                "title",
                "contract_value",
                "cost_value",
                "closed_at",
                "outcome",
                "region_code",
            )
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(key.encode()).hexdigest()


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def load_bundle(session: Session, bundle: dict) -> dict[str, int]:
    stats = {"regions": 0, "positions": 0, "dictionary": 0, "deals": 0, "deals_skipped": 0}

    coefficients = {c["region_code"]: c for c in bundle.get("coefficients", [])}
    for r in bundle.get("regions", []):
        row = session.scalar(select(CalcRegion).where(CalcRegion.code == r["code"]))
        if row is None:
            row = CalcRegion(code=r["code"])
            session.add(row)
            stats["regions"] += 1
        coef = coefficients.get(r["code"])
        row.name = r["name"]
        row.parent_code = r.get("parent_code")
        row.coefficient = _dec(coef["coefficient"]) if coef else None
        row.note = coef.get("note") if coef else None

    for p in bundle.get("positions", []):
        row = session.scalar(select(CalcPosition).where(CalcPosition.code == p["code"]))
        if row is None:
            row = CalcPosition(code=p["code"])
            session.add(row)
            stats["positions"] += 1
        row.name = p["name"]
        row.system_group = p.get("system_group") or "Прочее"
        row.unit = p.get("unit") or "шт."
        row.price = _dec(p.get("price_typical") or p.get("price") or 0)
        row.complexity_coef = _dec(p.get("complexity_coef") or 1)
        row.price_period = p.get("price_period")
        row.is_synthetic = bool(p.get("is_synthetic", False))

    for dict_code, items in (bundle.get("dictionaries") or {}).items():
        if dict_code not in DICTIONARIES:
            continue
        for order, item in enumerate(items):
            row = session.scalar(
                select(CalcDictionary).where(
                    CalcDictionary.dict_code == dict_code, CalcDictionary.code == item["code"]
                )
            )
            if row is None:
                row = CalcDictionary(dict_code=dict_code, code=item["code"])
                session.add(row)
                stats["dictionary"] += 1
            row.label = item["label"]
            row.value = _dec(item.get("value"))
            row.description = item.get("description")
            row.order_no = order

    session.flush()
    known = set(session.scalars(select(CalcDeal.fingerprint)))
    for d in bundle.get("historical_deals", []):
        fp = _fingerprint(d)
        if fp in known:
            stats["deals_skipped"] += 1
            continue
        known.add(fp)
        closed = d.get("closed_at")
        session.add(
            CalcDeal(
                title=d["title"][:512],
                fingerprint=fp,
                project_type=d.get("project_type") or "dispatching",
                object_type=d.get("object_type"),
                scale=d.get("scale"),
                area_m2=_dec(d.get("area_m2")),
                project_level=d.get("project_level"),
                region_code=d.get("region_code"),
                cost_value=_dec(d.get("cost_value")),
                contract_value=_dec(d["contract_value"]),
                outcome=d.get("outcome"),
                retro_price_basis=d.get("retro_price_basis") or "synthetic",
                financing_scheme=d.get("financing_scheme"),
                payment_scheme=d.get("payment_scheme"),
                closed_at=date.fromisoformat(closed) if closed else None,
                scope_json=d.get("scope"),
            )
        )
        stats["deals"] += 1
    session.commit()
    from modules.deal_calculator.artifacts import prepare

    prepare(session)
    session.commit()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--create-all", action="store_true")
    args = parser.parse_args()

    from app.db.session import SessionLocal, engine

    if args.create_all:
        create_tables(engine, everything=True)
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    with SessionLocal() as session:
        stats = load_bundle(session, bundle)
    print(f"калькулятор: {stats}")


if __name__ == "__main__":
    main()
