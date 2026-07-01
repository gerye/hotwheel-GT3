from __future__ import annotations

from typing import Optional
from sqlmodel import Session, select
from app.models import Car, Team, Season
from app.enums import CarStatus, SeasonStatus, ACTIVE_STATUSES
from app.services import seasons as ssvc
from app.services import salary as sal, budget as bud


class MarketError(Exception):
    pass


def reference_season(session: Session) -> Optional[Season]:
    """转会参照赛季:最近一个已结束赛季;无则当前进行中赛季。"""
    ended = session.exec(select(Season).where(Season.status == SeasonStatus.FINISHED)
                         .order_by(Season.id.desc())).first()
    return ended or ssvc.get_active_season(session)


def season_pair(session: Session):
    """返回 (本赛季来源季 id, 下赛季预计来源季 id)。
    本赛季的预算/薪资由"上一个已结束赛季"决定;下赛季预计由"进行中赛季"实时推算。
    任一不存在则为 None(由 budget/salary 当作基础值处理)。"""
    active = ssvc.get_active_season(session)
    finished = session.exec(select(Season).where(
        Season.status == SeasonStatus.FINISHED).order_by(Season.id.desc())).all()
    if active is not None:
        return (finished[0].id if finished else None, active.id)
    nxt = finished[0].id if finished else None
    cur = finished[1].id if len(finished) > 1 else None
    return (cur, nxt)


def committed_salary(session: Session, team_id: int, season_id: int) -> int:
    cars = session.exec(select(Car).where(Car.team_id == team_id,
                        Car.status.in_(ACTIVE_STATUSES))).all()
    return sum(sal.compute_salary(session, c, season_id) for c in cars)


def headroom(session: Session, team_id: int, season_id: int) -> int:
    team = session.get(Team, team_id)
    return bud.compute_budget(session, team, season_id) - committed_salary(session, team_id, season_id)


def assign_car(session: Session, car: Car, team_id: int, status: CarStatus) -> None:
    """底层:把 car 落到 team(现役状态),不做校验(校验在调用方)。"""
    car.team_id = team_id
    car.status = status
    session.add(car)
    session.commit()


def release_car(session: Session, car: Car) -> None:
    """底层:解约 car → 未签约、无车队。"""
    car.team_id = None
    car.status = CarStatus.UNSIGNED
    session.add(car)
    session.commit()
