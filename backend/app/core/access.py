"""Ownership checks shared by HTTP routes for both estimate tables."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Deal, DealEstimate, User
from modules.deal_calculator.models import CalcEstimate


def calculator_estimate(session: Session, estimate_id: int, user: User) -> CalcEstimate:
    row = session.get(CalcEstimate, estimate_id)
    if row is None or (user.role != "admin" and row.author_id != user.id):
        raise HTTPException(404, "Расчёт не найден")
    return row


def legacy_estimate(session: Session, estimate_id: int, user: User) -> DealEstimate:
    row = session.get(DealEstimate, estimate_id)
    deal = session.get(Deal, row.deal_id) if row else None
    if row is None or deal is None or (user.role != "admin" and deal.author_id != user.id):
        raise HTTPException(404, "Расчёт не найден")
    return row
