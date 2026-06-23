from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlmodel import create_engine, select
from sqlmodel.pool import StaticPool
from app import db
from app.models import Car
from app.enums import Category, TeamType, CarStatus, ProLevel, RaceFormat
from app.services import (cars as csvc, teams as tsvc, seasons as ssvc,
                          tournament as T)


# ---------- 状态与车队绑定 ----------

def test_create_without_team_is_unsigned(session):
    c = csvc.create_car(session, nickname="独", category=Category.GT3,
                        brand="B", casting="", description="", team_id=None)
    assert c.status == CarStatus.UNSIGNED


def test_create_with_team_is_active(session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="队")
    c = csvc.create_car(session, nickname="现", category=Category.GT3,
                        brand="B", casting="", description="", team_id=t.id)
    assert c.status == CarStatus.ACTIVE


def test_join_team_via_update_becomes_active(session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="队")
    c = csvc.create_car(session, nickname="x", category=Category.GT3,
                        brand="B", casting="", description="", team_id=None)
    csvc.update_car(session, c.id, team_id=t.id)
    session.refresh(c)
    assert c.status == CarStatus.ACTIVE


def test_leave_team_via_update_becomes_unsigned(session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="队")
    c = csvc.create_car(session, nickname="x", category=Category.GT3,
                        brand="B", casting="", description="", team_id=t.id)
    csvc.update_car(session, c.id, team_id=None)
    session.refresh(c)
    assert c.status == CarStatus.UNSIGNED


# ---------- change_status 状态机 ----------

def test_active_to_retired_then_back(session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="队")
    c = csvc.create_car(session, nickname="x", category=Category.GT3,
                        brand="B", casting="", description="", team_id=t.id)
    csvc.change_status(session, c.id, CarStatus.RETIRED)
    session.refresh(c); assert c.status == CarStatus.RETIRED
    csvc.change_status(session, c.id, CarStatus.ACTIVE)
    session.refresh(c); assert c.status == CarStatus.ACTIVE


def test_unsigned_cannot_go_active_directly(session):
    c = csvc.create_car(session, nickname="x", category=Category.GT3,
                        brand="B", casting="", description="", team_id=None)
    with pytest.raises(csvc.CarValidationError):
        csvc.change_status(session, c.id, CarStatus.ACTIVE)


def test_unsigned_cannot_retire(session):
    c = csvc.create_car(session, nickname="x", category=Category.GT3,
                        brand="B", casting="", description="", team_id=None)
    with pytest.raises(csvc.CarValidationError):
        csvc.change_status(session, c.id, CarStatus.RETIRED)


def test_set_unsigned_clears_team(session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="队")
    c = csvc.create_car(session, nickname="x", category=Category.GT3,
                        brand="B", casting="", description="", team_id=t.id)
    csvc.change_status(session, c.id, CarStatus.UNSIGNED)
    session.refresh(c)
    assert c.status == CarStatus.UNSIGNED and c.team_id is None


# ---------- 名额:退役不占,只数现役 ----------

def test_retired_does_not_occupy_slot(session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    a = csvc.create_car(session, nickname="a", category=Category.GT3,
                        brand="法拉利", casting="", description="", team_id=t.id)
    csvc.create_car(session, nickname="b", category=Category.GT3,
                    brand="法拉利", casting="", description="", team_id=t.id)
    csvc.change_status(session, a.id, CarStatus.RETIRED)   # 现役变 1
    # 现在可以再加一个现役(b + 新车 = 2 现役,a 退役不计)
    c = csvc.create_car(session, nickname="c", category=Category.GT3,
                        brand="法拉利", casting="", description="", team_id=t.id)
    assert c.status == CarStatus.ACTIVE


def test_active_cap_blocks_third_active(session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    for n in "ab":
        csvc.create_car(session, nickname=n, category=Category.GT3,
                        brand="法拉利", casting="", description="", team_id=t.id)
    with pytest.raises(tsvc.TeamValidationError):
        csvc.create_car(session, nickname="c", category=Category.GT3,
                        brand="法拉利", casting="", description="", team_id=t.id)


def test_reactivate_blocked_when_full(session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    a = csvc.create_car(session, nickname="a", category=Category.GT3,
                        brand="法拉利", casting="", description="", team_id=t.id)
    csvc.create_car(session, nickname="b", category=Category.GT3,
                    brand="法拉利", casting="", description="", team_id=t.id)
    csvc.change_status(session, a.id, CarStatus.RETIRED)
    csvc.create_car(session, nickname="c", category=Category.GT3,
                    brand="法拉利", casting="", description="", team_id=t.id)  # 2 现役
    with pytest.raises(tsvc.TeamValidationError):
        csvc.change_status(session, a.id, CarStatus.ACTIVE)   # 复出受阻


# ---------- 专业赛资格仅现役 ----------

def test_pro_race_rejects_non_active(session):
    ssvc.start_season(session, name="2026 S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="队")
    cars = []
    for i in range(4):
        ti = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name=f"q{i}")
        c = csvc.create_car(session, nickname=f"c{i}", category=Category.GT3,
                            brand="B", casting="", description="", team_id=ti.id)
        cars.append(c)
    csvc.change_status(session, cars[0].id, CarStatus.RETIRED)   # 一个退役
    with pytest.raises(ValueError):
        T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                      format=RaceFormat.SOLO, car_ids=[c.id for c in cars], seed=1)


# ---------- 迁移回填 ----------

def test_migration_backfills_status_from_team():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    with eng.begin() as conn:
        # 旧 car 表:无 status 列
        conn.execute(text(
            'CREATE TABLE car (id INTEGER PRIMARY KEY, nickname VARCHAR, '
            'image_path VARCHAR, casting VARCHAR, brand VARCHAR, category VARCHAR, '
            'description VARCHAR, team_id INTEGER, season_mmr FLOAT, '
            'historical_mmr FLOAT)'))
        conn.execute(text(
            "INSERT INTO car (nickname, category, team_id, season_mmr, historical_mmr) "
            "VALUES ('有队', 'GT3', 1, 1500, 1500), ('无队', 'GT3', NULL, 1500, 1500)"))
    db.set_engine(eng)
    try:
        db.init_db()
        rows = dict(eng.connect().execute(text(
            "SELECT nickname, status FROM car")).fetchall())
        assert rows["有队"] == "现役"
        assert rows["无队"] == "未签约"
    finally:
        db.set_engine(None)
