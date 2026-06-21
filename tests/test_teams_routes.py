from __future__ import annotations

from fastapi.testclient import TestClient
from app.main import app
from sqlmodel import select
from app.models import Team

client = TestClient(app)


def test_create_factory_team(engine, session):
    r = client.post("/teams", data={"type": "厂商车队", "brand": "法拉利", "name": ""},
                    follow_redirects=False)
    assert r.status_code in (302, 303)
    t = session.exec(select(Team)).one()
    assert t.name == "法拉利车队"


def test_create_factory_without_brand_errors(engine, session):
    r = client.post("/teams", data={"type": "厂商车队", "brand": "", "name": ""})
    assert r.status_code == 200
    assert "品牌" in r.text


def test_create_independent_team(engine, session):
    r = client.post("/teams", data={"type": "独立车队", "brand": "", "name": "车库突击队"},
                    follow_redirects=False)
    assert r.status_code in (302, 303)
    assert session.exec(select(Team)).one().name == "车库突击队"
