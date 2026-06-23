from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import select
from app.main import app
from app.models import Team, Car
from app.enums import Category, TeamType, ProLevel, RaceFormat
from app.services import (teams as tsvc, cars as csvc, seasons as ssvc,
                          tournament as T)

client = TestClient(app)


# ---------- specific_name 组合 ----------

def test_factory_specific_name_with_alias(session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None,
                         alias_f1="大王八")
    assert t.name == "法拉利车队"                       # 宏观名不变
    assert t.specific_name(Category.F1) == "法拉利大王八F1车队"


def test_factory_specific_name_without_alias(session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    assert t.specific_name(Category.GT3) == "法拉利GT3车队"


def test_independent_specific_name_with_alias(session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None,
                         name="车库突击队", alias_gt3="闪电")
    assert t.specific_name(Category.GT3) == "车库突击队闪电GT3"


def test_independent_specific_name_without_alias(session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None,
                         name="车库突击队")
    assert t.specific_name(Category.ROAD) == "车库突击队公路车"


# ---------- 服务存别名 ----------

def test_update_team_sets_alias(session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    tsvc.update_team(session, t.id, type=TeamType.FACTORY, brand="法拉利",
                     name=None, alias_f1="大王八")
    session.refresh(t)
    assert t.alias_f1 == "大王八"
    assert t.specific_name(Category.F1) == "法拉利大王八F1车队"


def test_empty_alias_stored_as_none(session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None,
                         alias_f1="")
    assert t.alias_f1 is None


# ---------- 路由:具体名出现在赛车页;宏观名出现在列表/榜 ----------

def test_car_detail_shows_specific_name(engine, session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None,
                         alias_f1="大王八")
    c = csvc.create_car(session, nickname="红1", category=Category.F1,
                        brand="法拉利", casting="", description="", team_id=t.id)
    r = client.get(f"/cars/{c.id}")
    assert "法拉利大王八F1车队" in r.text


def test_database_and_standings_use_macro_name(engine, session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None,
                         alias_f1="大王八")
    r = client.get("/database/teams")
    assert "法拉利车队" in r.text and "大王八" not in r.text


def test_team_race_detail_shows_specific_names(engine, session):
    ssvc.start_season(session, name="2026 S1")
    t1 = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None,
                          alias_f1="大王八")
    t2 = tsvc.create_team(session, type=TeamType.FACTORY, brand="保时捷", name=None,
                          alias_f1="小乌龟")
    for t, b in [(t1, "法拉利"), (t2, "保时捷")]:
        for i in range(2):
            csvc.create_car(session, nickname=f"{b}{i}", category=Category.F1,
                            brand=b, casting="", description="", team_id=t.id)
    race = T.create_team_race(session, category=Category.F1, pro_level=ProLevel.PRO,
                              team_ids=[t1.id, t2.id], seed=1)
    r = client.get(f"/races/{race.id}")
    assert "法拉利大王八F1车队" in r.text and "保时捷小乌龟F1车队" in r.text
