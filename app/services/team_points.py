from __future__ import annotations

from sqlmodel import Session, select
from app.models import Race, RaceEntry, TeamPointEntry, Car
from app.enums import RaceFormat
from app.config import TP_ADVANCE, TP_PODIUM, TP_TEAM_MULTIPLIER
from app.services import racestats


def _car_team(session: Session, race_id: int, car_id: int):
    return racestats.car_team(session, race_id, car_id)


def car_points(session: Session, race_id: int) -> dict:
    """car_id -> 该车在本场赚到的车队积分(晋级 + 决赛圈名次)。"""
    adv = racestats.car_advancements(session, race_id)
    podium = racestats.car_podium(session, race_id)
    pts = {}
    for cid, a in adv.items():
        pts[cid] = a * TP_ADVANCE + TP_PODIUM.get(podium.get(cid), 0)
    return pts


def award(session: Session, race: Race) -> None:
    """把本场车队积分写入 TeamPointEntry(来源记录)。"""
    mult = TP_TEAM_MULTIPLIER if race.format == RaceFormat.TEAM else 1
    by_team: dict[int, int] = {}
    sources: dict[int, list] = {}
    for cid, p in car_points(session, race.id).items():
        if p == 0:
            continue
        tid = _car_team(session, race.id, cid)
        if tid is None:
            continue
        by_team[tid] = by_team.get(tid, 0) + p * mult
        nick = session.get(Car, cid).nickname
        sources.setdefault(tid, []).append(f"{nick} +{p * mult}")
    for tid, total in by_team.items():
        desc = race.format.value + ":" + "、".join(sources[tid])
        session.add(TeamPointEntry(season_id=race.season_id, team_id=tid,
                    points=total, source_car_id=None, race_id=race.id, description=desc))
    session.commit()
