from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlmodel import Session, select
from app.models import Season
from app.enums import SeasonStatus


class SeasonError(Exception):
    pass


def get_active_season(session: Session) -> Optional[Season]:
    return session.exec(
        select(Season).where(Season.status == SeasonStatus.ACTIVE)
    ).first()


def start_season(session: Session, *, name: str) -> Season:
    if get_active_season(session) is not None:
        raise SeasonError("已有进行中的赛季,请先结束当前赛季")
    s = Season(name=name, status=SeasonStatus.ACTIVE)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def end_season(session: Session, season_id: int) -> Season:
    s = session.get(Season, season_id)
    if s is None:
        raise SeasonError("赛季不存在")
    if s.status == SeasonStatus.FINISHED:
        raise SeasonError("赛季已结束")
    # 计划三:在此处插入 MMR 快照与车队积分清零钩子
    s.status = SeasonStatus.FINISHED
    s.ended_at = datetime.utcnow()
    session.add(s)
    session.commit()
    session.refresh(s)
    return s
