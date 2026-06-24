from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import select
from app.main import app
from app.models import (Car, Team, Season, Race, RaceRound, Group, GroupMember,
                        Heat, HeatResult)
from app.enums import Category, ProLevel, RaceFormat, TeamType
from app.services import (seasons as ssvc, teams as tsvc, cars as csvc,
                          tournament as T, admin as admin_svc)

client = TestClient(app)


def _seed(session):
    ssvc.start_season(session, name="2026 S1")
    ids = []
    for i in range(4):
        t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name=f"q{i}")
        ids.append(csvc.create_car(session, nickname=f"c{i}", category=Category.GT3,
                   brand="B", casting="", description="", team_id=t.id).id)
    T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                  format=RaceFormat.SOLO, car_ids=ids, seed=1)


def test_wipe_clears_everything(session):
    _seed(session)
    admin_svc.wipe_all_data(session)
    for model in (Car, Team, Season, Race, RaceRound, Group, GroupMember,
                  Heat, HeatResult):
        assert session.exec(select(model)).all() == []


def test_wipe_via_route(engine, session):
    _seed(session)
    r = client.post("/admin/wipe-all", follow_redirects=False)
    assert r.status_code == 303 and "/database" in r.headers["location"]
    session.expire_all()
    assert session.exec(select(Car)).all() == []
    assert session.exec(select(Season)).all() == []


def test_group_card_shows_member_car_strip(engine, session):
    _seed(session)
    race = session.exec(select(Race)).one()
    r = client.get(f"/races/{race.id}")
    assert r.status_code == 200
    # 组内小车名字出现在卡片(图片条 + 积分榜)
    assert "c0" in r.text
