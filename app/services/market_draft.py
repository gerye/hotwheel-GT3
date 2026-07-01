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


def _has_long(session: Session, team_id: int, category: Category) -> bool:
    return len(_long_cars(session, team_id, category)) > 0


def _unlocked_long_categories(session: Session, team_id: int, draft: MarketDraft) -> set:
    done = locked_categories(draft)
    return {cat for cat in Category
            if _has_long(session, team_id, cat) and cat not in done}


def lock_category(session: Session, team_id: int, category: Category,
                  slot_car_ids: list) -> None:
    draft = get_draft(session)
    if draft is None or draft.current_team_id != team_id:
        raise DraftError("该车队不是当前处理的车队")
    if category in locked_categories(draft):
        raise DraftError("该类别已锁定,请先解锁")
    team = session.get(Team, team_id)
    ref_id = draft.reference_season_id
    chosen_ids = [cid for cid in slot_car_ids if cid]

    # ① 顺序:含长期车类别必须先锁
    if not _has_long(session, team_id, category):
        pending = _unlocked_long_categories(session, team_id, draft)
        if pending:
            raise DraftError("请先锁定含长期车的类别:"
                             + "、".join(c.value for c in pending))

    long_ids = {c.id for c in _long_cars(session, team_id, category)}
    if not long_ids.issubset(set(chosen_ids)):
        raise DraftError("长期车不可移除,必须保留在阵容中")
    if len(chosen_ids) > MAX_CARS_PER_CATEGORY:
        raise DraftError("每类别最多 2 个现役")

    pool = {row["car"].id: row for row in category_pool(session, team_id, category)}
    # ② 品牌 + 来源合法:非长期的选中车必须来自候选池
    for cid in chosen_ids:
        if cid in long_ids:
            continue
        if cid not in pool:
            raise DraftError("所选车不在候选池中(品牌/归属/退役不合法)")

    # ④ 数量 + 逃生阀
    has_long = bool(long_ids)
    if len(chosen_ids) == MAX_CARS_PER_CATEGORY:
        pass
    elif len(chosen_ids) <= 1:
        addable = [r for cid2, r in pool.items()
                   if cid2 not in chosen_ids and r["affordable"]]
        if addable:
            raise DraftError("该类别可补强,不能停在不足 2 个现役")
        if not has_long and len(chosen_ids) == 1:
            raise DraftError("无长期车的类别必须是 0 或 2 个现役")

    # ⑤ 预算
    other_salary = 0
    for c in session.exec(select(Car).where(Car.team_id == team_id,
                          Car.status.in_(ACTIVE_STATUSES))).all():
        if c.category != category:
            other_salary += sal.compute_salary(session, c, ref_id)
    chosen_salary = sum(sal.compute_salary(session, session.get(Car, cid), ref_id)
                        for cid in chosen_ids)
    budget = market.bud.compute_budget(session, team, ref_id)
    long_only_salary = sum(sal.compute_salary(session, session.get(Car, cid), ref_id)
                           for cid in long_ids)
    over = other_salary + chosen_salary > budget
    long_only_over = other_salary + long_only_salary > budget
    if over and not (has_long and chosen_salary == long_only_salary and long_only_over):
        raise DraftError("超出预算")

    # ---- 应用:释放本类别现有非长期现役,再签入选中的非长期车 ----
    for c in session.exec(select(Car).where(Car.team_id == team_id,
                          Car.category == category,
                          Car.status.in_(ACTIVE_STATUSES))).all():
        if c.id not in long_ids:
            market.release_car(session, c)
    for cid in chosen_ids:
        if cid in long_ids:
            continue
        market.assign_car(session, session.get(Car, cid), team_id, CarStatus.SHORT)

    cats = locked_categories(draft)
    cats.add(category)
    draft.locked_categories = ",".join(c.value for c in cats)
    session.add(draft); session.commit()
