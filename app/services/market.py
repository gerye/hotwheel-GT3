from __future__ import annotations

from typing import Optional
from sqlmodel import Session, select
from app.models import Car, Team, Season
from app.enums import CarStatus, ContractType, SeasonStatus
from app.services import market_snapshot, seasons as ssvc


class MarketError(Exception):
    pass


def reference_season(session: Session) -> Optional[Season]:
    """转会参照赛季:最近一个已结束赛季;无则当前进行中赛季。"""
    ended = session.exec(select(Season).where(Season.status == SeasonStatus.FINISHED)
                         .order_by(Season.id.desc())).first()
    return ended or ssvc.get_active_season(session)


def open_market(session: Session) -> None:
    """开盘:按参照赛季写预算/薪资快照;释放所有短期合同车为自由身。"""
    ref = reference_season(session)
    if ref is not None:
        market_snapshot.snapshot_season(session, ref.id)
    for car in session.exec(select(Car).where(
            Car.contract == ContractType.SHORT)).all():
        car.team_id = None
        car.status = CarStatus.UNSIGNED
        car.contract = None
        session.add(car)
    session.commit()


from app.enums import TeamType
from app.services import salary as sal, budget as bud
from app.config import MAX_CARS_PER_CATEGORY


def committed_salary(session: Session, team_id: int, season_id: int) -> int:
    cars = session.exec(select(Car).where(Car.team_id == team_id,
                        Car.status == CarStatus.ACTIVE)).all()
    return sum(sal.compute_salary(session, c, season_id) for c in cars)


def headroom(session: Session, team_id: int, season_id: int) -> int:
    team = session.get(Team, team_id)
    return bud.compute_budget(session, team, season_id) - committed_salary(session, team_id, season_id)


def _active_in_category(session: Session, team_id: int, category) -> int:
    return len(session.exec(select(Car).where(
        Car.team_id == team_id, Car.category == category,
        Car.status == CarStatus.ACTIVE)).all())


def sign(session: Session, car_id: int, team_id: int, season_id: int) -> None:
    car = session.get(Car, car_id)
    team = session.get(Team, team_id)
    if car is None or team is None:
        raise MarketError("赛车或车队不存在")
    if team.type == TeamType.FACTORY and car.brand != team.brand:
        raise MarketError(f"厂商车队「{team.name}」只能签品牌「{team.brand}」的车")
    if _active_in_category(session, team_id, car.category) >= MAX_CARS_PER_CATEGORY:
        raise MarketError(f"{team.name} 在 {car.category.value} 已有 2 个现役")
    price = sal.compute_salary(session, car, season_id)
    if price > headroom(session, team_id, season_id):
        raise MarketError(f"预算不足:{car.nickname} 薪资 {price} > 余额 "
                          f"{headroom(session, team_id, season_id)}")
    car.team_id = team_id
    car.status = CarStatus.ACTIVE
    car.contract = ContractType.SHORT     # 自由市场签下默认短期
    session.add(car); session.commit()


def release(session: Session, car_id: int) -> None:
    car = session.get(Car, car_id)
    if car is None:
        raise MarketError("赛车不存在")
    car.team_id = None
    car.status = CarStatus.UNSIGNED
    car.contract = None
    session.add(car); session.commit()
