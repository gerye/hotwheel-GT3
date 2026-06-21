from __future__ import annotations

from typing import Optional
from sqlmodel import Session, select
from app.models import Car, Team
from app.enums import Category
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
               team_id: Optional[int], image_path: Optional[str] = None) -> Car:
    _check_unique_nickname(session, nickname)
    car = Car(nickname=nickname, category=category, brand=brand, casting=casting,
              description=description, image_path=image_path)
    if team_id is not None:
        team = session.get(Team, team_id)
        if team is None:
            raise CarValidationError("车队不存在")
        tsvc.check_can_assign(session, car=car, team=team)
        car.team_id = team_id
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
    if new_team_id is not None:
        team = session.get(Team, new_team_id)
        if team is None:
            raise CarValidationError("车队不存在")
        tsvc.check_can_assign(session, car=car, team=team)
    car.team_id = new_team_id
    session.add(car)
    session.commit()
    session.refresh(car)
    return car
