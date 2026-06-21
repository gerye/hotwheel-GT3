from __future__ import annotations

from typing import Optional
from sqlmodel import Session, select
from app.models import (Race, RaceEntry, RaceRound, Group, GroupMember,
                        Heat, HeatResult)
from app.enums import Category, ProLevel, RaceFormat, RaceStatus
from app.services import grouping, lineup, seasons as ssvc


def create_race(session: Session, *, category: Category, pro_level: ProLevel,
                format: RaceFormat, car_ids: list[int],
                seed: Optional[int] = None) -> Race:
    season = ssvc.get_active_season(session)
    if season is None:
        raise ValueError("没有进行中的赛季,请先开启赛季")
    grouping.group_sizes(len(car_ids))   # 提前校验数量,非法直接抛 GroupingError
    race = Race(season_id=season.id, category=category, pro_level=pro_level,
                format=format, status=RaceStatus.IN_PROGRESS)
    session.add(race); session.commit(); session.refresh(race)
    for cid in car_ids:
        session.add(RaceEntry(race_id=race.id, car_id=cid))
    session.commit()
    _build_round(session, race, number=1, car_ids=car_ids, seed=seed)
    return race


def _build_round(session: Session, race: Race, *, number: int,
                 car_ids: list[int], seed: Optional[int]) -> RaceRound:
    is_final = len(car_ids) <= 4
    rnd = RaceRound(race_id=race.id, number=number, is_final=is_final)
    session.add(rnd); session.commit(); session.refresh(rnd)
    planned = grouping.partition(car_ids, seed=seed)
    for pg in planned:
        group = Group(round_id=rnd.id, label=pg.label)
        session.add(group); session.commit(); session.refresh(group)
        for cid in pg.members:
            session.add(GroupMember(group_id=group.id, car_id=cid))
        session.commit()
        _build_heats(session, group, pg.members)
    return rnd


def _build_heats(session: Session, group: Group, members: list[int]) -> None:
    schedule = lineup.build_lineup(members)   # 4 场 × 4 道
    for hi, lane_to_car in enumerate(schedule, start=1):
        heat = Heat(group_id=group.id, number=hi, recorded=False)
        session.add(heat); session.commit(); session.refresh(heat)
        for lane_idx, car in enumerate(lane_to_car, start=1):
            if car is not None:
                session.add(HeatResult(heat_id=heat.id, car_id=car,
                                       lane=lane_idx, rank=None))
        session.commit()
