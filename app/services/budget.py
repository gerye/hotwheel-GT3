from __future__ import annotations

from typing import Optional
from sqlmodel import Session, select
from app.models import Team, Race
from app.enums import ProLevel, RaceFormat, RaceStatus
from app.config import (BUDGET_BASE, POINT_VALUE, CHAMP_BUDGET_SOLO, CHAMP_BUDGET_TEAM)
from app.services import standings, racestats


def _championships(session: Session, team: Team, season_id: int):
    """返回 (单人赛夺冠次数, 车队赛夺冠次数) —— 该队的车在该赛季夺冠的比赛。"""
    solo, team_cnt = 0, 0
    races = session.exec(select(Race).where(Race.season_id == season_id,
                         Race.pro_level == ProLevel.PRO,
                         Race.status == RaceStatus.FINISHED)).all()
    for race in races:
        ranking = racestats.final_ranking(session, race.id)
        if not ranking:
            continue
        champ_car = ranking[0]
        if racestats.car_team(session, race.id, champ_car) == team.id:
            if race.format == RaceFormat.TEAM:
                team_cnt += 1
            else:
                solo += 1
    return solo, team_cnt


def compute_budget(session: Session, team: Team, season_id: Optional[int]) -> int:
    if season_id is None:          # 无往季数据 → 基础预算
        return BUDGET_BASE
    pts = standings.team_season_points(session, team.id, season_id)
    solo, team_cnt = _championships(session, team, season_id)
    return (BUDGET_BASE + POINT_VALUE * pts
            + CHAMP_BUDGET_SOLO * solo + CHAMP_BUDGET_TEAM * team_cnt)
