from __future__ import annotations

from fastapi.testclient import TestClient
from app.main import app
from app.enums import Category, TeamType
from app.services import teams as tsvc
from sqlmodel import select
from app.models import Car

client = TestClient(app)


def test_create_car_via_form(engine, session):
    r = client.post("/cars", data={
        "nickname": "红色闪电", "category": "GT3", "brand": "法拉利",
        "casting": "C01", "description": "稳", "team_id": "",
    }, follow_redirects=False)
    assert r.status_code in (302, 303)
    got = session.exec(select(Car).where(Car.nickname == "红色闪电")).one()
    assert got.brand == "法拉利"


def test_create_car_duplicate_shows_error(engine, session):
    client.post("/cars", data={"nickname": "红色闪电", "category": "GT3",
                "brand": "法拉利", "casting": "", "description": "", "team_id": ""})
    r = client.post("/cars", data={"nickname": "红色闪电", "category": "F1",
                "brand": "法拉利", "casting": "", "description": "", "team_id": ""})
    assert r.status_code == 200
    assert "已存在" in r.text


def test_create_car_factory_mismatch_shows_error(engine, session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    r = client.post("/cars", data={"nickname": "蓝鲨", "category": "GT3",
                "brand": "保时捷", "casting": "", "description": "", "team_id": str(t.id)})
    assert r.status_code == 200
    assert "品牌" in r.text


def test_edit_car(engine, session):
    client.post("/cars", data={"nickname": "红色闪电", "category": "GT3",
                "brand": "法拉利", "casting": "", "description": "", "team_id": ""})
    car = session.exec(select(Car)).one()
    r = client.post(f"/cars/{car.id}/edit", data={"nickname": "红色闪电2",
                "category": "GT3", "brand": "法拉利", "casting": "", "description": "改",
                "team_id": ""}, follow_redirects=False)
    assert r.status_code in (302, 303)
    session.refresh(car)
    assert car.nickname == "红色闪电2"
