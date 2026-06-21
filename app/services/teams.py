from __future__ import annotations

from typing import Optional
from sqlmodel import Session, select
from app.models import Team, Car
from app.enums import TeamType, Category
from app.config import MAX_CARS_PER_CATEGORY


class TeamValidationError(Exception):
    pass


def create_team(session: Session, *, type: TeamType,
                brand: Optional[str], name: Optional[str]) -> Team:
    if type == TeamType.FACTORY:
        if not brand:
            raise TeamValidationError("厂商车队必须填写品牌")
        team = Team(type=type, brand=brand, name=f"{brand}车队")
    else:
        if not name:
            raise TeamValidationError("独立车队必须填写名称")
        team = Team(type=type, brand=None, name=name)
    session.add(team)
    session.commit()
    session.refresh(team)
    return team


def _category_count(session: Session, team_id: int, category: Category,
                    exclude_car_id: Optional[int]) -> int:
    rows = session.exec(
        select(Car).where(Car.team_id == team_id, Car.category == category)
    ).all()
    return len([c for c in rows if c.id != exclude_car_id])


def check_can_assign(session: Session, *, car: Car, team: Team) -> None:
    if team.type == TeamType.FACTORY and car.brand != team.brand:
        raise TeamValidationError(
            f"厂商车队「{team.name}」只能加入品牌为「{team.brand}」的赛车")
    count = _category_count(session, team.id, car.category, exclude_car_id=car.id)
    if count >= MAX_CARS_PER_CATEGORY:
        raise TeamValidationError(
            f"车队「{team.name}」在 {car.category.value} 类别已满 "
            f"({MAX_CARS_PER_CATEGORY} 辆)")
