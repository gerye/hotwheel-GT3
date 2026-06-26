import pytest
from app.models import Team, Car
from app.enums import TeamType, Category, CarStatus
from app.services import teams as svc


def _factory(session, brand="法拉利"):
    t = Team(type=TeamType.FACTORY, brand=brand, name=f"{brand}车队")
    session.add(t); session.commit(); session.refresh(t)
    return t


def test_factory_team_name_is_brand_plus_suffix(session):
    t = svc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    assert t.name == "法拉利车队"


def test_independent_team_keeps_given_name(session):
    t = svc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="车库突击队")
    assert t.name == "车库突击队"


def test_factory_requires_brand(session):
    with pytest.raises(svc.TeamValidationError):
        svc.create_team(session, type=TeamType.FACTORY, brand=None, name=None)


def test_independent_requires_name(session):
    with pytest.raises(svc.TeamValidationError):
        svc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="")


def test_assign_car_brand_mismatch_to_factory_rejected(session):
    t = _factory(session, "法拉利")
    car = Car(nickname="蓝鲨", category=Category.GT3, brand="保时捷")
    session.add(car); session.commit(); session.refresh(car)
    with pytest.raises(svc.TeamValidationError):
        svc.check_can_assign(session, car=car, team=t)


def test_assign_car_brand_match_to_factory_ok(session):
    t = _factory(session, "法拉利")
    car = Car(nickname="红色闪电", category=Category.GT3, brand="法拉利")
    session.add(car); session.commit(); session.refresh(car)
    svc.check_can_assign(session, car=car, team=t)


def test_category_capacity_enforced(session):
    t = _factory(session, "法拉利")
    for i in range(2):
        c = Car(nickname=f"红{i}", category=Category.GT3, brand="法拉利",
                team_id=t.id, status=CarStatus.LONG)
        session.add(c)
    session.commit()
    third = Car(nickname="红3", category=Category.GT3, brand="法拉利")
    session.add(third); session.commit(); session.refresh(third)
    with pytest.raises(svc.TeamValidationError):
        svc.check_can_assign(session, car=third, team=t)


def test_capacity_counts_per_category(session):
    t = _factory(session, "法拉利")
    for i in range(2):
        session.add(Car(nickname=f"g{i}", category=Category.GT3, brand="法拉利", team_id=t.id))
    session.commit()
    f1car = Car(nickname="f1", category=Category.F1, brand="法拉利")
    session.add(f1car); session.commit(); session.refresh(f1car)
    svc.check_can_assign(session, car=f1car, team=t)
