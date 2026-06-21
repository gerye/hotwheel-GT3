from __future__ import annotations

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_home_redirects_to_database(engine):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "/database" in r.headers["location"]


from sqlmodel import select
from app.enums import Category, TeamType
from app.services import cars as csvc, teams as tsvc


def test_database_lists_cars(engine, session):
    csvc.create_car(session, nickname="红色闪电", category=Category.GT3,
                    brand="法拉利", casting="C01", description="", team_id=None)
    r = client.get("/database")
    assert r.status_code == 200
    assert "红色闪电" in r.text


def test_database_search_filters(engine, session):
    csvc.create_car(session, nickname="红色闪电", category=Category.GT3,
                    brand="法拉利", casting="C01", description="", team_id=None)
    csvc.create_car(session, nickname="蓝鲨", category=Category.GT3,
                    brand="保时捷", casting="A99", description="", team_id=None)
    r = client.get("/database/cars?q=保时捷")
    assert "蓝鲨" in r.text and "红色闪电" not in r.text


def test_database_teams_tab(engine, session):
    tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    r = client.get("/database/teams")
    assert "法拉利车队" in r.text


def test_car_detail_shows_fields(engine, session):
    csvc.create_car(session, nickname="红色闪电", category=Category.GT3,
                    brand="法拉利", casting="C01", description="弯道稳定", team_id=None)
    from app.models import Car
    cid = session.exec(select(Car)).one().id
    r = client.get(f"/cars/{cid}")
    assert "红色闪电" in r.text and "弯道稳定" in r.text and "1500" in r.text


def test_team_detail_shows_capacity(engine, session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    csvc.create_car(session, nickname="红色闪电", category=Category.GT3,
                    brand="法拉利", casting="", description="", team_id=t.id)
    r = client.get(f"/teams/{t.id}")
    assert "法拉利车队" in r.text and "红色闪电" in r.text


from app.enums import ProLevel, RaceFormat
from app.services import tournament as T, standings as st, seasons as ssvc


def test_team_detail_shows_points_and_sources(engine, session):
    s = ssvc.start_season(session, name="2026 S1")
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    c = csvc.create_car(session, nickname="法1", category=Category.GT3,
                        brand="法拉利", casting="", description="", team_id=t.id)
    st.award_solo(session, season_id=s.id, race_id=1, ranking=[c.id])
    r = client.get(f"/teams/{t.id}")
    assert "5" in r.text and "单人锦标赛第 1 名" in r.text
