from app.enums import Category, CarStatus, TeamType
from app.services import teams as tsvc, cars as csvc
from app.models import Car


def _team(session):
    return tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="t")


def test_create_with_team_uses_signed_status(session):
    t = _team(session)
    c = csvc.create_car(session, nickname="a", category=Category.GT3, brand="B",
                        casting="", description="", team_id=t.id,
                        signed_status=CarStatus.SHORT)
    assert session.get(Car, c.id).status == CarStatus.SHORT


def test_create_without_team_unsigned(session):
    c = csvc.create_car(session, nickname="b", category=Category.GT3, brand="B",
                        casting="", description="", team_id=None)
    assert c.status == CarStatus.UNSIGNED


def test_edit_change_contract(session):
    t = _team(session)
    c = csvc.create_car(session, nickname="c", category=Category.GT3, brand="B",
                        casting="", description="", team_id=t.id,
                        signed_status=CarStatus.LONG)
    csvc.update_car(session, c.id, team_id=t.id, signed_status=CarStatus.SHORT)
    assert session.get(Car, c.id).status == CarStatus.SHORT


def test_edit_keeps_retired(session):
    t = _team(session)
    c = csvc.create_car(session, nickname="d", category=Category.GT3, brand="B",
                        casting="", description="", team_id=t.id,
                        signed_status=CarStatus.LONG)
    csvc.change_status(session, c.id, CarStatus.RETIRED)
    csvc.update_car(session, c.id, team_id=t.id, signed_status=CarStatus.LONG,
                    casting="x")
    assert session.get(Car, c.id).status == CarStatus.RETIRED   # 编辑不改变退役
