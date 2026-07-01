from __future__ import annotations

from sqlmodel import select
from app.enums import Category, TeamType, CarStatus
from app.services import seasons as ssvc, teams as tsvc, cars as csvc
from app.services import market, market_draft as md
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


def _seed_two_teams(session):
    ssvc.start_season(session, name="S1")
    ta = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="A")
    tb = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="B")
    long_a = csvc.create_car(session, nickname="A长", category=Category.GT3, brand="X",
                             casting="", description="", team_id=ta.id, signed_status=CarStatus.LONG)
    short_a = csvc.create_car(session, nickname="A短", category=Category.GT3, brand="X",
                              casting="", description="", team_id=ta.id, signed_status=CarStatus.SHORT)
    return ta, tb, long_a, short_a


def test_open_snapshots_all_and_does_not_release(session):
    ta, tb, long_a, short_a = _seed_two_teams(session)
    d = md.open_draft(session)
    session.expire_all()
    assert session.get(Car, short_a.id).status == CarStatus.SHORT
    snaps = session.exec(select(DraftCarSnapshot).where(
        DraftCarSnapshot.draft_id == d.id)).all()
    assert len(snaps) == 2
    assert md.get_draft(session).id == d.id


def test_reset_restores_from_snapshot(session):
    ta, tb, long_a, short_a = _seed_two_teams(session)
    md.open_draft(session)
    market.release_car(session, session.get(Car, short_a.id))
    md.reset_draft(session)
    session.expire_all()
    c = session.get(Car, short_a.id)
    assert c.team_id == ta.id and c.status == CarStatus.SHORT
    d = md.get_draft(session)
    assert d.locked_team_ids == "" and d.current_team_id is None
