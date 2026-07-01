from __future__ import annotations

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
