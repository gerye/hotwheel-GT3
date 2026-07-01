from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import select
from app.enums import Category, TeamType, CarStatus, ProLevel, RaceFormat, RaceStatus
from app.models import (Car, Team, Season, Race, RaceRound, Group, Heat, HeatResult,
                        MarketDraft)
from app.services import seasons as ssvc, teams as tsvc, cars as csvc
from app.services import insights


def test_lane_constants_exist():
    from app import config
    assert config.LANE_MIN_SAMPLE >= 1
    assert config.LANE_BIAS_THRESHOLD > 0


def _finished_heat(session, *, season_id, category, rows, status=RaceStatus.FINISHED):
    """建一场(1 轮 1 组 1 heat)比赛并写入 rows=[(lane, rank, dnf), ...] 的 HeatResult。"""
    race = Race(season_id=season_id, category=category, pro_level=ProLevel.PRO,
                format=RaceFormat.SOLO, status=status)
    session.add(race); session.commit(); session.refresh(race)
    rnd = RaceRound(race_id=race.id, number=1)
    session.add(rnd); session.commit(); session.refresh(rnd)
    grp = Group(round_id=rnd.id, label="A")
    session.add(grp); session.commit(); session.refresh(grp)
    heat = Heat(group_id=grp.id, number=1, recorded=True)
    session.add(heat); session.commit(); session.refresh(heat)
    for lane, rank, dnf in rows:
        session.add(HeatResult(heat_id=heat.id, car_id=1, lane=lane, rank=rank, dnf=dnf))
    session.commit()
    return race


def test_lane_stats_avg_rank_and_rates(session):
    sid = ssvc.start_season(session, name="S1").id
    _finished_heat(session, season_id=sid, category=Category.GT3,
                   rows=[(1, 1, False), (2, 2, False), (3, 3, False)])
    _finished_heat(session, season_id=sid, category=Category.GT3,
                   rows=[(1, None, True), (2, 2, False), (3, 3, False), (4, 4, False)])
    st = insights.lane_stats(session)
    by_lane = {l["lane"]: l for l in st["lanes"]}
    assert st["total_results"] == 7
    assert by_lane[1]["n"] == 2
    assert abs(by_lane[1]["avg_rank"] - 1.0) < 1e-9
    assert abs(by_lane[1]["dnf_rate"] - 0.5) < 1e-9
    assert abs(by_lane[1]["win_rate"] - 0.5) < 1e-9
    assert by_lane[4]["n"] == 1 and abs(by_lane[4]["avg_rank"] - 4.0) < 1e-9


def test_lane_stats_ignores_unfinished_and_filters(session):
    s1 = ssvc.start_season(session, name="S1").id
    _finished_heat(session, season_id=s1, category=Category.GT3, rows=[(1, 1, False)])
    _finished_heat(session, season_id=s1, category=Category.GT3,
                   rows=[(2, 1, False)], status=RaceStatus.IN_PROGRESS)
    _finished_heat(session, season_id=s1, category=Category.F1, rows=[(3, 1, False)])
    assert insights.lane_stats(session)["total_results"] == 2
    assert insights.lane_stats(session, category=Category.GT3)["total_results"] == 1
    assert insights.lane_stats(session, season_id=s1, category=Category.F1)["total_results"] == 1


def test_lane_stats_verdict_flags_bias(session):
    sid = ssvc.start_season(session, name="S1").id
    for _ in range(12):
        _finished_heat(session, season_id=sid, category=Category.GT3,
                       rows=[(1, 1, False), (2, 4, False)])
    v = insights.lane_stats(session)["verdict"]
    assert v["enough_sample"] is True
    assert v["biased"] is True
    assert v["fastest_lane"] == 1 and v["slowest_lane"] == 2


def test_lane_stats_empty(session):
    st = insights.lane_stats(session)
    assert st["total_results"] == 0
    assert st["verdict"]["enough_sample"] is False
    assert all(l["avg_rank"] is None for l in st["lanes"])


def test_overview_counts(session):
    ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    csvc.create_car(session, nickname="a", category=Category.GT3, brand="X",
                    casting="", description="", team_id=t.id, signed_status=CarStatus.LONG)
    csvc.create_car(session, nickname="b", category=Category.GT3, brand="X",
                    casting="", description="", team_id=None)
    oc = insights.overview_counts(session)
    assert oc["cars"] == 2 and oc["teams"] == 1
    assert oc["active"] == 1 and oc["unsigned"] == 1 and oc["seasons"] == 1


def test_health_all_ok_when_clean(session):
    ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    csvc.create_car(session, nickname="a", category=Category.GT3, brand="X",
                    casting="", description="", team_id=t.id, signed_status=CarStatus.LONG)
    checks = {c["key"]: c for c in insights.health_checks(session)}
    assert all(c["ok"] for c in checks.values())


def test_health_detects_status_inconsistency(session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    bad = Car(nickname="矛盾", category=Category.GT3, brand="X",
              team_id=t.id, status=CarStatus.UNSIGNED)
    session.add(bad); session.commit()
    c = {x["key"]: x for x in insights.health_checks(session)}["status_consistency"]
    assert c["ok"] is False and any("矛盾" in it["label"] for it in c["items"])
    assert c["items"][0]["href"] == f"/cars/{bad.id}"


def test_health_detects_capacity_over(session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    for i in range(3):
        session.add(Car(nickname=f"c{i}", category=Category.GT3, brand="X",
                        team_id=t.id, status=CarStatus.LONG))
    session.commit()
    c = {x["key"]: x for x in insights.health_checks(session)}["capacity"]
    assert c["ok"] is False and any(t.name in it["label"] for it in c["items"])


def test_health_detects_brand_mismatch(session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    session.add(Car(nickname="错牌", category=Category.GT3, brand="保时捷",
                    team_id=t.id, status=CarStatus.LONG))
    session.commit()
    c = {x["key"]: x for x in insights.health_checks(session)}["brand_mismatch"]
    assert c["ok"] is False and any("错牌" in it["label"] for it in c["items"])


def test_health_detects_unfinished_and_draft(session):
    sid = ssvc.start_season(session, name="S1").id
    session.add(Race(season_id=sid, category=Category.GT3, pro_level=ProLevel.PRO,
                     format=RaceFormat.SOLO, status=RaceStatus.IN_PROGRESS))
    session.add(MarketDraft(reference_season_id=sid, tiebreak_seed=1))
    session.commit()
    checks = {x["key"]: x for x in insights.health_checks(session)}
    assert checks["unfinished_races"]["ok"] is False
    assert checks["open_draft"]["ok"] is False
    assert checks["unfinished_races"]["severity"] == "warn"


from app.main import app


def test_insights_routes_registered():
    paths = {r.path for r in app.routes}
    assert {"/insights", "/lanes", "/health"} <= paths


_client = TestClient(app)


def test_routes_render(engine, session):
    sid = ssvc.start_season(session, name="S1").id
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    csvc.create_car(session, nickname="a", category=Category.GT3, brand="X",
                    casting="", description="", team_id=t.id, signed_status=CarStatus.LONG)
    assert _client.get("/insights").status_code == 200
    r = _client.get("/lanes")
    assert r.status_code == 200 and "平均名次" in r.text
    assert _client.get("/lanes", params={"category": "GT3", "season_id": sid}).status_code == 200
    h = _client.get("/health")
    assert h.status_code == 200 and "状态一致性" in h.text
