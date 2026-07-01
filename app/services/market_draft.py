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


def _max_active_mmr(session: Session, team_id: int) -> float:
    rows = session.exec(select(Car).where(Car.team_id == team_id,
                        Car.status.in_(ACTIVE_STATUSES))).all()
    return max((c.season_mmr for c in rows), default=float("-inf"))


def priority_key(session: Session, draft: MarketDraft, team_id: int, ref_id: int):
    """排序键:余额高→积分高→最高MMR高→固定随机。取负实现降序。"""
    hr = market.headroom(session, team_id, ref_id)
    pts = st.team_season_points(session, team_id, ref_id)
    mmr = _max_active_mmr(session, team_id)
    rnd = random.Random("%d-%d" % (draft.tiebreak_seed, team_id)).random()
    return (-hr, -pts, -mmr, rnd)


def draft_queue(session: Session) -> list:
    draft = get_draft(session)
    if draft is None:
        return []
    ref_id = draft.reference_season_id
    locked = locked_team_ids(draft)
    rows = []
    for t in session.exec(select(Team)).all():
        rows.append({
            "team": t,
            "headroom": market.headroom(session, t.id, ref_id),
            "points": st.team_season_points(session, t.id, ref_id),
            "locked": t.id in locked,
            "is_current": t.id == draft.current_team_id,
            "_key": priority_key(session, draft, t.id, ref_id),
        })
    rows.sort(key=lambda r: (r["locked"], r["_key"]))
    for r in rows:
        r.pop("_key")
    return rows
