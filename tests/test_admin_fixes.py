from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import select
from app.main import app
from app.models import Car, Team
from app.enums import Category, TeamType
from app.services import (cars as csvc, teams as tsvc, seasons as ssvc,
                          standings as st)

client = TestClient(app)


# ---------- 车队编辑(issue 1) ----------

def test_team_edit_form_loads(engine, session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="老名")
    r = client.get(f"/teams/{t.id}/edit")
    assert r.status_code == 200 and "老名" in r.text


def test_team_edit_updates_name(engine, session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="老名")
    r = client.post(f"/teams/{t.id}/edit",
                    data={"type": "独立车队", "brand": "", "name": "新名"},
                    follow_redirects=False)
    assert r.status_code in (302, 303)
    session.refresh(t)
    assert t.name == "新名"


def test_team_edit_to_factory_brand_mismatch_shows_error(engine, session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="队")
    csvc.create_car(session, nickname="保时捷车", category=Category.GT3,
                    brand="保时捷", casting="", description="", team_id=t.id)
    r = client.post(f"/teams/{t.id}/edit",
                    data={"type": "厂商车队", "brand": "法拉利", "name": ""})
    assert r.status_code == 200 and "品牌" in r.text


# ---------- 删除(issue 3) ----------

def test_delete_team_detaches_members(engine, session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    c = csvc.create_car(session, nickname="法1", category=Category.GT3,
                        brand="法拉利", casting="", description="", team_id=t.id)
    tid, cid = t.id, c.id
    r = client.post(f"/teams/{t.id}/delete", follow_redirects=False)
    assert r.status_code in (302, 303)
    session.expire_all()           # 丢弃身份映射缓存,强制从库重读
    assert session.get(Team, tid) is None
    assert session.get(Car, cid).team_id is None   # 车未被删,只是脱离车队


def test_delete_car_removes_it(engine, session):
    c = csvc.create_car(session, nickname="待删", category=Category.GT3,
                        brand="B", casting="", description="", team_id=None)
    cid = c.id
    r = client.post(f"/cars/{cid}/delete", follow_redirects=False)
    assert r.status_code in (302, 303)
    session.expire_all()
    assert session.get(Car, cid) is None


# ---------- 一键重置 MMR(issue 4) ----------

def test_reset_season_mmr(engine, session):
    c = csvc.create_car(session, nickname="车", category=Category.GT3,
                        brand="B", casting="", description="", team_id=None)
    c.season_mmr = 1700.0
    c.historical_mmr = 1700.0
    session.add(c); session.commit()
    r = client.post("/standings/reset-season", follow_redirects=False)
    assert r.status_code in (302, 303)
    session.refresh(c)
    assert c.season_mmr == 1500.0
    assert c.historical_mmr == 1700.0   # 历史不动


def test_reset_historical_mmr(engine, session):
    c = csvc.create_car(session, nickname="车", category=Category.GT3,
                        brand="B", casting="", description="", team_id=None)
    c.season_mmr = 1700.0
    c.historical_mmr = 1700.0
    session.add(c); session.commit()
    r = client.post("/standings/reset-historical", follow_redirects=False)
    assert r.status_code in (302, 303)
    session.refresh(c)
    assert c.historical_mmr == 1500.0
    assert c.season_mmr == 1700.0       # 赛季不动
