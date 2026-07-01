from __future__ import annotations

from sqlmodel import select
from app.enums import Category, TeamType, CarStatus
from app.services import seasons as ssvc, teams as tsvc, cars as csvc
from app.services import market
from app.models import Car, MarketDraft, DraftCarSnapshot


def test_models_exist_and_default():
    d = MarketDraft(reference_season_id=1, tiebreak_seed=7)
    assert d.current_team_id is None
    assert d.locked_team_ids == "" and d.locked_categories == ""
    snap = DraftCarSnapshot(draft_id=1, car_id=1, orig_team_id=None,
                            orig_status=CarStatus.UNSIGNED)
    assert snap.orig_status == CarStatus.UNSIGNED
