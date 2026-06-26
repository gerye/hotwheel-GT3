from __future__ import annotations

from sqlmodel import Session, select
from app.models import Race, RaceRound, Group, GroupMember, HeatResult, Heat
from app.enums import RaceStatus
from app.services import scoring


def _is_finished(session: Session, race_id: int) -> bool:
    race = session.get(Race, race_id)
    return race is not None and race.status == RaceStatus.FINISHED


def _rounds(session: Session, race_id: int):
    return session.exec(select(RaceRound).where(RaceRound.race_id == race_id)
                        .order_by(RaceRound.number)).all()


def _group_results(session: Session, group_id: int) -> dict:
    out: dict[int, list] = {}
    for h in session.exec(select(Heat).where(Heat.group_id == group_id)).all():
        for r in session.exec(select(HeatResult).where(HeatResult.heat_id == h.id)).all():
            out.setdefault(r.car_id, []).append(r.rank)
    return out


def car_appearances(session: Session, race_id: int) -> dict:
    """car_id -> 出现过的轮号集合。"""
    appear: dict[int, set] = {}
    for rnd in _rounds(session, race_id):
        for g in session.exec(select(Group).where(Group.round_id == rnd.id)).all():
            for m in session.exec(select(GroupMember)
                                  .where(GroupMember.group_id == g.id)).all():
                appear.setdefault(m.car_id, set()).add(rnd.number)
    return appear


def car_advancements(session: Session, race_id: int) -> dict:
    return {cid: len(rs) - 1 for cid, rs in car_appearances(session, race_id).items()}


def final_group(session: Session, race_id: int):
    rnd = _rounds(session, race_id)[-1]
    return session.exec(select(Group).where(Group.round_id == rnd.id)).first()


def final_ranking(session: Session, race_id: int) -> list:
    # 比赛未结束 → 尚无最终名次(避免拿进行中某轮的小组充数)
    if not _is_finished(session, race_id):
        return []
    g = final_group(session, race_id)
    if g is None:
        return []
    totals = scoring.group_totals(_group_results(session, g.id))
    return scoring.final_ranking(totals)


def car_achievements(session: Session, race_id: int) -> dict:
    """car_id -> {champion: bool, finalist: bool}。比赛未结束则均为 False。"""
    appearances = car_appearances(session, race_id)
    if not _is_finished(session, race_id):
        return {cid: {"champion": False, "finalist": False} for cid in appearances}
    fg = final_group(session, race_id)
    finalists = {m.car_id for m in session.exec(select(GroupMember)
                 .where(GroupMember.group_id == fg.id)).all()}
    ranking = final_ranking(session, race_id)
    champ = ranking[0] if ranking else None
    return {cid: {"champion": cid == champ, "finalist": cid in finalists}
            for cid in appearances}


def car_podium(session: Session, race_id: int) -> dict:
    """car_id -> 名次(1/2/3),仅决赛圈前三;其余不在 dict。"""
    ranking = final_ranking(session, race_id)
    return {cid: i + 1 for i, cid in enumerate(ranking[:3])}
