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


def _highest_unlocked(session: Session, draft: MarketDraft) -> Optional[int]:
    for row in draft_queue(session):
        if not row["locked"]:
            return row["team"].id
    return None


def enter_team(session: Session, team_id: int) -> None:
    draft = get_draft(session)
    if draft is None:
        raise DraftError("尚未开盘")
    if draft.current_team_id is not None:
        raise DraftError("已有正在处理的车队,请先确认或重置")
    if team_id in locked_team_ids(draft):
        raise DraftError("该车队已确认")
    if team_id != _highest_unlocked(session, draft):
        raise DraftError("必须先处理当前余额最高的车队")
    for c in session.exec(select(Car).where(Car.team_id == team_id,
                          Car.status == CarStatus.SHORT)).all():
        market.release_car(session, c)
    draft.current_team_id = team_id
    draft.locked_categories = ""
    session.add(draft); session.commit()


def _brand_ok(team: Team, car: Car) -> bool:
    return not (team.type == TeamType.FACTORY
                and not tsvc.is_brandless(car.brand)
                and car.brand != team.brand)


def _long_cars(session: Session, team_id: int, category: Category):
    return session.exec(select(Car).where(Car.team_id == team_id,
        Car.category == category, Car.status == CarStatus.LONG)).all()


def category_pool(session: Session, team_id: int, category: Category) -> list:
    """某 (队,类别) 一个自由槽的候选池:自由身 + 未确认他队短期 + 本队该类别现有现役;
    去掉长期车、已确认队的车、退役车;按品牌过滤;标注是否买得起。"""
    draft = get_draft(session)
    ref_id = draft.reference_season_id
    locked = locked_team_ids(draft)
    team = session.get(Team, team_id)
    hr = market.headroom(session, team_id, ref_id)
    out, seen = [], set()
    for c in session.exec(select(Car).where(Car.category == category)).all():
        if c.id in seen or c.status == CarStatus.RETIRED:
            continue
        if c.status == CarStatus.LONG:
            continue
        own = (c.team_id == team_id)
        free = (c.team_id is None)
        other_short = (c.team_id is not None and c.team_id != team_id
                       and c.team_id not in locked and c.status == CarStatus.SHORT)
        if not (own or free or other_short):
            continue
        if not _brand_ok(team, c):
            continue
        price = sal.compute_salary(session, c, ref_id)
        out.append({"car": c, "salary": price, "affordable": price <= hr})
        seen.add(c.id)
    out.sort(key=lambda r: sal._season_mmr(session, r["car"], ref_id), reverse=True)
    return out


def category_recommendation(session: Session, team_id: int, category: Category) -> dict:
    draft = get_draft(session)
    ref_id = draft.reference_season_id
    longs = _long_cars(session, team_id, category)
    long_ids = [c.id for c in longs]
    keep = list(long_ids)
    for snap in session.exec(select(DraftCarSnapshot).where(
            DraftCarSnapshot.draft_id == draft.id)).all():
        car = session.get(Car, snap.car_id)
        if (snap.orig_team_id == team_id and car is not None
                and car.category == category and snap.orig_status == CarStatus.SHORT):
            keep.append(car.id)
    keep = keep[:MAX_CARS_PER_CATEGORY]
    strengthen = list(long_ids)
    hr = market.headroom(session, team_id, ref_id)
    for row in category_pool(session, team_id, category):
        if len(strengthen) >= MAX_CARS_PER_CATEGORY:
            break
        if row["car"].id in strengthen:
            continue
        if row["salary"] <= hr:
            strengthen.append(row["car"].id)
            hr -= row["salary"]
    return {"keep": keep, "can_disband": len(longs) == 0, "strengthen": strengthen}
