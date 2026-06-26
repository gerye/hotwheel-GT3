import pytest
from sqlmodel import select
from app.enums import Category, CarStatus, TeamType
from app.services import seasons as ssvc, teams as tsvc, cars as csvc
from app.models import Car


def _team(session, name="t"):
    return tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name=name)


def test_long_short_toggle(session):
    t = _team(session)
    c = csvc.create_car(session, nickname="a", category=Category.GT3, brand="B",
                        casting="", description="", team_id=t.id,
                        signed_status=CarStatus.LONG)
    csvc.change_status(session, c.id, CarStatus.SHORT)
    assert session.get(Car, c.id).status == CarStatus.SHORT


def test_retire_then_comeback_pick_contract(session):
    t = _team(session)
    c = csvc.create_car(session, nickname="b", category=Category.GT3, brand="B",
                        casting="", description="", team_id=t.id,
                        signed_status=CarStatus.LONG)
    csvc.change_status(session, c.id, CarStatus.RETIRED)
    assert session.get(Car, c.id).status == CarStatus.RETIRED
    csvc.change_status(session, c.id, CarStatus.SHORT)   # 复出选短期
    assert session.get(Car, c.id).status == CarStatus.SHORT


def test_unsigned_cannot_sign_directly(session):
    c = csvc.create_car(session, nickname="c", category=Category.GT3, brand="B",
                        casting="", description="", team_id=None)
    with pytest.raises(csvc.CarValidationError):
        csvc.change_status(session, c.id, CarStatus.LONG)


def test_comeback_blocked_when_full(session):
    t = _team(session)
    # 先建一辆并退役它(腾出名额),再填满 2 个现役,最后让它复出 → 应被名额拦截
    r = csvc.create_car(session, nickname="r", category=Category.GT3, brand="B",
                        casting="", description="", team_id=t.id,
                        signed_status=CarStatus.LONG)
    csvc.change_status(session, r.id, CarStatus.RETIRED)   # r 退役,腾出名额
    for i in range(2):
        csvc.create_car(session, nickname=f"x{i}", category=Category.GT3, brand="B",
                        casting="", description="", team_id=t.id,
                        signed_status=CarStatus.LONG)       # 2 个现役占满
    with pytest.raises(tsvc.TeamValidationError):
        csvc.change_status(session, r.id, CarStatus.LONG)  # 名额满,复出失败
