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
    from app.models import RaceRound, Group, GroupMember, Heat
    s = ssvc.start_season(session, name="2026 S1")
    teams, ids = [], []
    for i in range(4):
        team = tsvc.create_team(session, type=TeamType.FACTORY,
                                brand=["法拉利", "保时捷", "奥迪", "宝马"][i], name=None)
        teams.append(team)
        ids.append(csvc.create_car(session, nickname=f"车{i}",
                   category=Category.GT3, brand=team.brand, casting="",
                   description="", team_id=team.id).id)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=ids, seed=1)
    rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).first()
    grp = session.exec(select(Group).where(Group.round_id == rnd.id)).first()
    members = [m.car_id for m in session.exec(select(GroupMember)
               .where(GroupMember.group_id == grp.id)).all()]
    for h in session.exec(select(Heat).where(Heat.group_id == grp.id)).all():
        T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(members)})
    result = T.advance_round(session, race.id)
    assert result.kind == "finished"
    champ_team_id = session.get(__import__("app.models", fromlist=["Car"]).Car,
                                result.ranking[0]).team_id
    r = client.get(f"/teams/{champ_team_id}")
    # 冠军车队:决赛圈名次1 → +4 分,来源记录里含车昵称与分值
    champ_car_id = result.ranking[0]
    champ_nick = session.get(__import__("app.models", fromlist=["Car"]).Car, champ_car_id).nickname
    assert "4" in r.text and champ_nick in r.text
