from __future__ import annotations

from typing import Optional
from sqlmodel import Session, select, or_
from app.models import Car, Team
from app.enums import Category


def search_cars(session: Session, query: str,
                category: Optional[Category] = None) -> list[Car]:
    stmt = select(Car)
    q = (query or "").strip()
    if q:
        like = f"%{q}%"
        team_ids = [t.id for t in session.exec(
            select(Team).where(Team.name.like(like))).all()]
        conditions = [
            Car.nickname.like(like),
            Car.brand.like(like),
            Car.casting.like(like),
            Car.description.like(like),
        ]
        if team_ids:
            conditions.append(Car.team_id.in_(team_ids))
        stmt = stmt.where(or_(*conditions))
    if category is not None:
        stmt = stmt.where(Car.category == category)
    return list(session.exec(stmt.order_by(Car.nickname)).all())


def search_teams(session: Session, query: str) -> list[Team]:
    stmt = select(Team)
    q = (query or "").strip()
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Team.name.like(like), Team.brand.like(like)))
    return list(session.exec(stmt.order_by(Team.name)).all())
