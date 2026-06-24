from __future__ import annotations

from sqlalchemy import delete
from sqlmodel import Session
from app.models import (HeatResult, Heat, TieBreak, GroupMember, Group,
                        RaceRound, RaceEntry, Race, TeamPointEntry,
                        CarSeasonMMR, Car, Season, Team)

# 按依赖顺序(子表在前)清空所有业务数据;保留表结构。
_WIPE_ORDER = [HeatResult, Heat, TieBreak, GroupMember, Group, RaceRound,
               RaceEntry, Race, TeamPointEntry, CarSeasonMMR, Car, Season, Team]


def wipe_all_data(session: Session) -> None:
    """删除所有赛季 / 比赛 / 赛车 / 车队记录(不可恢复)。"""
    for model in _WIPE_ORDER:
        session.exec(delete(model))
    session.commit()
