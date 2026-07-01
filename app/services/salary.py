from __future__ import annotations

import math
from typing import Optional
from sqlmodel import Session, select
from app.models import Car, Race, RaceEntry, CarSeasonMMR
from app.enums import ProLevel, RaceStatus
from app.config import (SALARY_BASE, SALARY_FLOOR, SALARY_MMR_UP, SALARY_MMR_DOWN,
                        SALARY_CHAMP, SALARY_FINALS, SALARY_LEGEND, LEGEND_TOP_PCT)
from app.services import racestats


def _season_mmr(session: Session, car: Car, season_id: int) -> float:
    snap = session.exec(select(CarSeasonMMR).where(
        CarSeasonMMR.season_id == season_id, CarSeasonMMR.car_id == car.id)).first()
    return snap.mmr if snap else car.season_mmr


def _mmr_component(mmr: float) -> int:
    if mmr >= 1500:
        return round((mmr - 1500) * SALARY_MMR_UP)
    return -round((1500 - mmr) * SALARY_MMR_DOWN)


def is_legend(session: Session, car: Car) -> bool:
    peers = session.exec(select(Car).where(Car.category == car.category)).all()
    if not peers:
        return False
    ordered = sorted(peers, key=lambda c: (c.historical_mmr, c.id), reverse=True)
    cutoff = max(1, math.ceil(len(ordered) * LEGEND_TOP_PCT))
    top_ids = {c.id for c in ordered[:cutoff]}
    return car.id in top_ids


def _season_achievements(session: Session, car: Car, season_id: int):
    champ, finals = 0, 0
    races = session.exec(select(Race).where(Race.season_id == season_id,
                         Race.pro_level == ProLevel.PRO,
                         Race.status == RaceStatus.FINISHED)).all()
    for race in races:
        entry = session.exec(select(RaceEntry).where(
            RaceEntry.race_id == race.id, RaceEntry.car_id == car.id)).first()
        if entry is None:
            continue
        ach = racestats.car_achievements(session, race.id).get(car.id)
        if not ach:
            continue
        if ach["champion"]:
            champ += 1
        elif ach["finalist"]:
            finals += 1
    return champ, finals


def compute_salary(session: Session, car: Car, season_id: Optional[int]) -> int:
    if season_id is None:          # 无往季数据 → MMR 视作 1500、无成绩
        mmr, champ, finals = 1500.0, 0, 0
    else:
        mmr = _season_mmr(session, car, season_id)
        champ, finals = _season_achievements(session, car, season_id)
    raw = (SALARY_BASE + _mmr_component(mmr)
           + SALARY_CHAMP * champ + SALARY_FINALS * finals
           + (SALARY_LEGEND if is_legend(session, car) else 0))
    return max(SALARY_FLOOR, raw)
