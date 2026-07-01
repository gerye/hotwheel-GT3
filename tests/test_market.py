from __future__ import annotations

from app.enums import Category, TeamType, CarStatus
from app.services import seasons as ssvc, teams as tsvc, cars as csvc
from app.services import market, salary as sal, budget as bud


def _seed(session):
    s = ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    long_car = csvc.create_car(session, nickname="老将", category=Category.GT3, brand="B",
                               casting="", description="", team_id=t.id,
                               signed_status=CarStatus.LONG)
    short_car = csvc.create_car(session, nickname="临时", category=Category.GT3, brand="B",
                                casting="", description="", team_id=t.id,
                                signed_status=CarStatus.SHORT)
    return s, t, long_car, short_car


def test_reference_season_prefers_finished(session):
    s, t, _, _ = _seed(session)
    assert market.reference_season(session).id == s.id
    ssvc.end_season(session, s.id)
    assert market.reference_season(session).id == s.id


def test_committed_salary_and_headroom(session):
    s, t, long_car, short_car = _seed(session)
    ssvc.end_season(session, s.id)
    ref = market.reference_season(session)
    committed = market.committed_salary(session, t.id, ref.id)
    expected = (sal.compute_salary(session, long_car, ref.id)
                + sal.compute_salary(session, short_car, ref.id))
    assert committed == expected
    assert market.headroom(session, t.id, ref.id) == \
        bud.compute_budget(session, t, ref.id) - committed


def test_committed_salary_excludes_retired(session):
    from app.services import cars as c2
    from app.models import Car
    s, t, long_car, short_car = _seed(session)
    c2.change_status(session, short_car.id, CarStatus.RETIRED)
    ssvc.end_season(session, s.id)
    ref = market.reference_season(session)
    assert market.committed_salary(session, t.id, ref.id) == \
        sal.compute_salary(session, session.get(Car, long_car.id), ref.id)
