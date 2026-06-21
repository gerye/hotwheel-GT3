from app.enums import Category, TeamType
from app.services import cars as csvc, teams as tsvc, search as ssvc


def _seed(session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    csvc.create_car(session, nickname="红色闪电", category=Category.GT3,
                    brand="法拉利", casting="Custom01", description="弯道稳定", team_id=t.id)
    csvc.create_car(session, nickname="蓝鲨", category=Category.GT3,
                    brand="保时捷", casting="Aero99", description="直线快", team_id=None)


def test_search_by_nickname(session):
    _seed(session)
    res = ssvc.search_cars(session, "红色")
    assert [c.nickname for c in res] == ["红色闪电"]


def test_search_by_brand(session):
    _seed(session)
    res = ssvc.search_cars(session, "保时捷")
    assert [c.nickname for c in res] == ["蓝鲨"]


def test_search_by_description(session):
    _seed(session)
    res = ssvc.search_cars(session, "弯道")
    assert [c.nickname for c in res] == ["红色闪电"]


def test_search_by_casting(session):
    _seed(session)
    res = ssvc.search_cars(session, "Aero")
    assert [c.nickname for c in res] == ["蓝鲨"]


def test_empty_query_returns_all(session):
    _seed(session)
    assert len(ssvc.search_cars(session, "")) == 2


def test_filter_by_category(session):
    _seed(session)
    res = ssvc.search_cars(session, "", category=Category.GT3)
    assert len(res) == 2
    res2 = ssvc.search_cars(session, "", category=Category.F1)
    assert res2 == []


def test_search_teams_by_name_and_brand(session):
    _seed(session)
    assert len(ssvc.search_teams(session, "法拉利")) == 1
    assert len(ssvc.search_teams(session, "")) == 1
