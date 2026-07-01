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


def test_assign_and_release_primitives(session):
    ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    c = csvc.create_car(session, nickname="c", category=Category.GT3, brand="X",
                        casting="", description="", team_id=None)
    market.assign_car(session, c, t.id, CarStatus.SHORT)
    session.expire_all()
    c = session.get(Car, c.id)
    assert c.team_id == t.id and c.status == CarStatus.SHORT
    market.release_car(session, c)
    session.expire_all()
    c = session.get(Car, c.id)
    assert c.team_id is None and c.status == CarStatus.UNSIGNED
