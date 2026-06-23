from __future__ import annotations

from typing import Optional
from sqlmodel import Session, select
from app.models import Team, Car
from app.enums import TeamType, Category, CarStatus
from app.config import MAX_CARS_PER_CATEGORY


class TeamValidationError(Exception):
    pass


def _apply_aliases(team: Team, alias_f1: Optional[str], alias_gt3: Optional[str],
                   alias_road: Optional[str]) -> None:
    team.alias_f1 = alias_f1 or None
    team.alias_gt3 = alias_gt3 or None
    team.alias_road = alias_road or None


def create_team(session: Session, *, type: TeamType,
                brand: Optional[str], name: Optional[str],
                alias_f1: Optional[str] = None, alias_gt3: Optional[str] = None,
                alias_road: Optional[str] = None) -> Team:
    if type == TeamType.FACTORY:
        if not brand:
            raise TeamValidationError("厂商车队必须填写品牌")
        team = Team(type=type, brand=brand, name=f"{brand}车队")
    else:
        if not name:
            raise TeamValidationError("独立车队必须填写名称")
        team = Team(type=type, brand=None, name=name)
    _apply_aliases(team, alias_f1, alias_gt3, alias_road)
    session.add(team)
    session.commit()
    session.refresh(team)
    return team


def update_team(session: Session, team_id: int, *, type: TeamType,
                brand: Optional[str], name: Optional[str],
                alias_f1: Optional[str] = None, alias_gt3: Optional[str] = None,
                alias_road: Optional[str] = None) -> Team:
    team = session.get(Team, team_id)
    if team is None:
        raise TeamValidationError("车队不存在")
    members = session.exec(select(Car).where(Car.team_id == team_id)).all()
    if type == TeamType.FACTORY:
        if not brand:
            raise TeamValidationError("厂商车队必须填写品牌")
        mismatch = [c for c in members if c.brand != brand]
        if mismatch:
            names = "、".join(c.nickname for c in mismatch)
            raise TeamValidationError(
                f"厂商车队品牌需与成员一致,但这些赛车品牌不符:{names}")
        team.type = type
        team.brand = brand
        team.name = f"{brand}车队"
    else:
        if not name:
            raise TeamValidationError("独立车队必须填写名称")
        team.type = type
        team.brand = None
        team.name = name
    _apply_aliases(team, alias_f1, alias_gt3, alias_road)
    session.add(team)
    session.commit()
    session.refresh(team)
    return team


def delete_team(session: Session, team_id: int) -> None:
    """删除车队:成员车的车队置空,清理积分记录,解除赛事引用。"""
    from app.models import TeamPointEntry, RaceEntry, Group
    team = session.get(Team, team_id)
    if team is None:
        raise TeamValidationError("车队不存在")
    for c in session.exec(select(Car).where(Car.team_id == team_id)).all():
        c.team_id = None
        c.status = CarStatus.UNSIGNED
        session.add(c)
    for e in session.exec(select(TeamPointEntry).where(
            TeamPointEntry.team_id == team_id)).all():
        session.delete(e)
    for r in session.exec(select(RaceEntry).where(
            RaceEntry.team_id == team_id)).all():
        r.team_id = None
        session.add(r)
    for g in session.exec(select(Group).where(Group.team_a_id == team_id)).all():
        g.team_a_id = None
        session.add(g)
    for g in session.exec(select(Group).where(Group.team_b_id == team_id)).all():
        g.team_b_id = None
        session.add(g)
    session.delete(team)
    session.commit()


def active_count(session: Session, team_id: int, category: Category,
                 exclude_car_id: Optional[int]) -> int:
    """车队在某类别下的现役车手数(退役不计)。"""
    rows = session.exec(
        select(Car).where(Car.team_id == team_id, Car.category == category,
                          Car.status == CarStatus.ACTIVE)
    ).all()
    return len([c for c in rows if c.id != exclude_car_id])


def check_active_capacity(session: Session, *, team: Team, category: Category,
                          exclude_car_id: Optional[int]) -> None:
    """现役名额校验:每类别最多 MAX_CARS_PER_CATEGORY 个现役。"""
    if active_count(session, team.id, category, exclude_car_id) >= MAX_CARS_PER_CATEGORY:
        raise TeamValidationError(
            f"车队「{team.name}」在 {category.value} 类别现役已满 "
            f"({MAX_CARS_PER_CATEGORY} 个现役车手),请先让某辆车退役")


def check_can_assign(session: Session, *, car: Car, team: Team) -> None:
    """把 car 加入 team(成为现役)前的校验。"""
    if team.type == TeamType.FACTORY and car.brand != team.brand:
        raise TeamValidationError(
            f"厂商车队「{team.name}」只能加入品牌为「{team.brand}」的赛车")
    check_active_capacity(session, team=team, category=car.category,
                          exclude_car_id=car.id)
