from __future__ import annotations

import random
from typing import Optional
from sqlmodel import Session, select
from app.models import Car, Team, MarketDraft, DraftCarSnapshot
from app.enums import Category, CarStatus, TeamType, ACTIVE_STATUSES
from app.config import MAX_CARS_PER_CATEGORY
from app.services import market, teams as tsvc, salary as sal, standings as st


class DraftError(Exception):
    pass


def get_draft(session: Session) -> Optional[MarketDraft]:
    return session.exec(select(MarketDraft).order_by(MarketDraft.id.desc())).first()


def open_draft(session: Session) -> MarketDraft:
    existing = get_draft(session)
    if existing is not None:
        return existing
    ref = market.reference_season(session)
    if ref is None:
        raise DraftError("没有可参照的赛季,无法开盘")
    draft = MarketDraft(reference_season_id=ref.id,
                        tiebreak_seed=random.randint(0, 10 ** 9))
    session.add(draft); session.commit(); session.refresh(draft)
    for c in session.exec(select(Car)).all():
        session.add(DraftCarSnapshot(draft_id=draft.id, car_id=c.id,
                    orig_team_id=c.team_id, orig_status=c.status))
    session.commit()
    return draft


def reset_draft(session: Session) -> None:
    draft = get_draft(session)
    if draft is None:
        return
    for snap in session.exec(select(DraftCarSnapshot).where(
            DraftCarSnapshot.draft_id == draft.id)).all():
        car = session.get(Car, snap.car_id)
        if car is not None:
            car.team_id = snap.orig_team_id
            car.status = snap.orig_status
            session.add(car)
    draft.current_team_id = None
    draft.locked_team_ids = ""
    draft.locked_categories = ""
    session.add(draft); session.commit()


def close_draft(session: Session) -> None:
    draft = get_draft(session)
    if draft is None:
        return
    for snap in session.exec(select(DraftCarSnapshot).where(
            DraftCarSnapshot.draft_id == draft.id)).all():
        session.delete(snap)
    session.delete(draft); session.commit()


def locked_team_ids(draft: MarketDraft) -> set:
    return {int(x) for x in draft.locked_team_ids.split(",") if x}


def locked_categories(draft: MarketDraft) -> set:
    return {Category(x) for x in draft.locked_categories.split(",") if x}
