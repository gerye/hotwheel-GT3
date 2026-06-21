import pytest
from app.models import Car
from app.enums import Category, TeamType
from app.services import cars as svc
from app.services import teams as tsvc


def test_create_car_minimal(session):
    car = svc.create_car(session, nickname="红色闪电", category=Category.GT3,
                         brand="法拉利", casting="Custom01", description="", team_id=None)
    assert car.id is not None
    assert car.season_mmr == 1500.0


def test_duplicate_nickname_rejected(session):
    svc.create_car(session, nickname="红色闪电", category=Category.GT3,
                   brand="法拉利", casting="", description="", team_id=None)
    with pytest.raises(svc.CarValidationError):
        svc.create_car(session, nickname="红色闪电", category=Category.F1,
                       brand="法拉利", casting="", description="", team_id=None)


def test_create_car_into_factory_brand_mismatch_rejected(session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    with pytest.raises(tsvc.TeamValidationError):
        svc.create_car(session, nickname="蓝鲨", category=Category.GT3,
                       brand="保时捷", casting="", description="", team_id=t.id)


def test_change_car_team_runs_constraint(session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    car = svc.create_car(session, nickname="蓝鲨", category=Category.GT3,
                         brand="保时捷", casting="", description="", team_id=None)
    with pytest.raises(tsvc.TeamValidationError):
        svc.update_car(session, car.id, team_id=t.id)


def test_change_car_team_to_none_ok(session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="独立队")
    car = svc.create_car(session, nickname="蓝鲨", category=Category.GT3,
                         brand="保时捷", casting="", description="", team_id=t.id)
    updated = svc.update_car(session, car.id, team_id=None)
    assert updated.team_id is None
