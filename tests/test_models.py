from __future__ import annotations

from app.enums import Category, TeamType, ProLevel, RaceFormat, SeasonStatus
from sqlmodel import select
from app.models import Car, Team


def test_category_values():
    assert Category.F1.value == "F1"
    assert Category.GT3.value == "GT3"
    assert Category.ROAD.value == "公路车"
    assert [c.value for c in Category] == ["F1", "GT3", "公路车"]


def test_team_and_level_enums():
    assert TeamType.FACTORY.value == "厂商车队"
    assert TeamType.INDEPENDENT.value == "独立车队"
    assert ProLevel.PRO.value == "专业"
    assert ProLevel.EXHIBITION.value == "表演"
    assert RaceFormat.SOLO.value == "单人锦标赛"
    assert RaceFormat.TEAM.value == "车队锦标赛"
    assert SeasonStatus.ACTIVE.value == "进行中"
    assert SeasonStatus.FINISHED.value == "已结束"


def test_can_insert_and_query_car(session):
    team = Team(type=TeamType.INDEPENDENT, name="车库突击队")
    session.add(team)
    session.commit()
    car = Car(nickname="红色闪电", category=Category.GT3, team_id=team.id)
    session.add(car)
    session.commit()
    got = session.exec(select(Car).where(Car.nickname == "红色闪电")).one()
    assert got.season_mmr == 1500.0
    assert got.team_id == team.id
