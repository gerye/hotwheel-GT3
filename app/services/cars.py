from __future__ import annotations

from typing import Optional
from sqlmodel import Session, select
from app.models import Car, Team
from app.enums import Category, CarStatus, ContractType
from app.services import teams as tsvc


class CarValidationError(Exception):
    pass


def _check_unique_nickname(session: Session, nickname: str,
                           exclude_id: Optional[int] = None) -> None:
    existing = session.exec(select(Car).where(Car.nickname == nickname)).first()
    if existing and existing.id != exclude_id:
        raise CarValidationError(f"昵称「{nickname}」已存在")


def create_car(session: Session, *, nickname: str, category: Category,
               brand: str, casting: str, description: str,
               team_id: Optional[int], image_path: Optional[str] = None,
               contract: Optional[ContractType] = None) -> Car:
    _check_unique_nickname(session, nickname)
    car = Car(nickname=nickname, category=category, brand=brand, casting=casting,
              description=description, image_path=image_path,
              status=CarStatus.UNSIGNED, contract=contract)
    if team_id is not None:
        team = session.get(Team, team_id)
        if team is None:
            raise CarValidationError("车队不存在")
        tsvc.check_can_assign(session, car=car, team=team)
        car.team_id = team_id
        car.status = CarStatus.ACTIVE   # 加入车队即现役
    session.add(car)
    session.commit()
    session.refresh(car)
    return car


def delete_car(session: Session, car_id: int) -> None:
    """删除赛车并清理其在赛事/荣誉中的引用。"""
    from app.models import (RaceEntry, GroupMember, HeatResult, CarSeasonMMR,
                            TeamPointEntry, TieBreak)
    car = session.get(Car, car_id)
    if car is None:
        raise CarValidationError("赛车不存在")
    for r in session.exec(select(RaceEntry).where(RaceEntry.car_id == car_id)).all():
        session.delete(r)
    for r in session.exec(select(GroupMember).where(
            GroupMember.car_id == car_id)).all():
        session.delete(r)
    for r in session.exec(select(HeatResult).where(
            HeatResult.car_id == car_id)).all():
        session.delete(r)
    for r in session.exec(select(CarSeasonMMR).where(
            CarSeasonMMR.car_id == car_id)).all():
        session.delete(r)
    for r in session.exec(select(TeamPointEntry).where(
            TeamPointEntry.source_car_id == car_id)).all():
        r.source_car_id = None
        session.add(r)
    for r in session.exec(select(TieBreak).where(
            TieBreak.winner_car_id == car_id)).all():
        r.winner_car_id = None
        session.add(r)
    session.delete(car)
    session.commit()


def update_car(session: Session, car_id: int, **fields) -> Car:
    car = session.get(Car, car_id)
    if car is None:
        raise CarValidationError("赛车不存在")
    if "nickname" in fields:
        _check_unique_nickname(session, fields["nickname"], exclude_id=car_id)
    new_team_id = fields.get("team_id", car.team_id)
    for k, v in fields.items():
        if k != "team_id":
            setattr(car, k, v)
    if new_team_id is None:
        # 移出车队 → 未签约
        car.team_id = None
        car.status = CarStatus.UNSIGNED
    else:
        team = session.get(Team, new_team_id)
        if team is None:
            raise CarValidationError("车队不存在")
        if car.status == CarStatus.UNSIGNED:
            # 未签约加入车队 → 现役(占名额,需校验)
            tsvc.check_can_assign(session, car=car, team=team)
            car.team_id = new_team_id
            car.status = CarStatus.ACTIVE
        else:
            # 已是现役/退役:现役换队仍要校验名额,退役不占名额
            if car.status == CarStatus.ACTIVE:
                tsvc.check_can_assign(session, car=car, team=team)
            elif team.type == tsvc.TeamType.FACTORY and car.brand != team.brand:
                raise tsvc.TeamValidationError(
                    f"厂商车队「{team.name}」只能加入品牌为「{team.brand}」的赛车")
            car.team_id = new_team_id
    session.add(car)
    session.commit()
    session.refresh(car)
    return car


def change_status(session: Session, car_id: int, new_status: CarStatus) -> Car:
    """按状态机切换赛车状态(含条件校验)。"""
    car = session.get(Car, car_id)
    if car is None:
        raise CarValidationError("赛车不存在")
    if new_status == car.status:
        return car
    if new_status == CarStatus.UNSIGNED:
        # 任意状态 → 未签约 = 移出车队
        car.team_id = None
        car.status = CarStatus.UNSIGNED
    elif new_status == CarStatus.RETIRED:
        if car.status != CarStatus.ACTIVE:
            raise CarValidationError("只有现役赛车才能退役")
        car.status = CarStatus.RETIRED
    elif new_status == CarStatus.ACTIVE:
        if car.status == CarStatus.UNSIGNED:
            raise CarValidationError("不能直接从未签约变为现役,请先在「编辑」里加入车队")
        # 退役 → 复出:需车队现役名额未满
        team = session.get(Team, car.team_id) if car.team_id else None
        if team is None:
            raise CarValidationError("该赛车没有车队,无法复出")
        tsvc.check_active_capacity(session, team=team, category=car.category,
                                   exclude_car_id=car.id)
        car.status = CarStatus.ACTIVE
    session.add(car)
    session.commit()
    session.refresh(car)
    return car
