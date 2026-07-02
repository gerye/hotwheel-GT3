from __future__ import annotations

import pytest
from app.enums import Category, CarStatus, ProLevel, RaceFormat, TeamType
from app.services import seasons as ssvc, teams as tsvc, cars as csvc, tournament as T
from app.routers.races import eligible_cars


def _setup(session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="t")
    active = csvc.create_car(session, nickname="现役", category=Category.GT3, brand="B",
                             casting="", description="", team_id=t.id,
                             signed_status=CarStatus.LONG)
    retired = csvc.create_car(session, nickname="退役", category=Category.GT3, brand="B",
                              casting="", description="", team_id=t.id,
                              signed_status=CarStatus.LONG)
    csvc.change_status(session, retired.id, CarStatus.RETIRED)
    unsigned = csvc.create_car(session, nickname="未签", category=Category.GT3, brand="B",
                               casting="", description="", team_id=None)
    return active, retired, unsigned


def test_retired_excluded_from_all_eligible_lists(session):
    ssvc.start_season(session, name="S1")
    active, retired, unsigned = _setup(session)
    pro = {c.id for c in eligible_cars(session, Category.GT3, pro=True)}
    exh = {c.id for c in eligible_cars(session, Category.GT3, pro=False)}
    assert retired.id not in pro and retired.id not in exh   # 退役:专业/表演都排除
    assert active.id in pro and active.id in exh
    assert unsigned.id not in pro                            # 专业赛不含未签约
    assert unsigned.id in exh                                # 表演赛仍含未签约


def test_create_exhibition_race_rejects_retired(session):
    ssvc.start_season(session, name="S1")
    active, retired, unsigned = _setup(session)
    with pytest.raises(ValueError):
        T.create_race(session, category=Category.GT3, pro_level=ProLevel.EXHIBITION,
                      format=RaceFormat.SOLO,
                      car_ids=[active.id, unsigned.id, retired.id], seed=1)
