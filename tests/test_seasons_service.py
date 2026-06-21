import pytest
from app.enums import SeasonStatus
from app.services import seasons as svc


def test_first_season_created_active(session):
    s = svc.start_season(session, name="2026 S1")
    assert s.status == SeasonStatus.ACTIVE
    assert svc.get_active_season(session).id == s.id


def test_cannot_start_second_active_season(session):
    svc.start_season(session, name="2026 S1")
    with pytest.raises(svc.SeasonError):
        svc.start_season(session, name="2026 S2")


def test_end_then_start_next(session):
    s1 = svc.start_season(session, name="2026 S1")
    svc.end_season(session, s1.id)
    assert svc.get_active_season(session) is None
    s2 = svc.start_season(session, name="2026 S2")
    assert s2.status == SeasonStatus.ACTIVE


def test_end_season_sets_ended_at(session):
    s1 = svc.start_season(session, name="2026 S1")
    ended = svc.end_season(session, s1.id)
    assert ended.status == SeasonStatus.FINISHED
    assert ended.ended_at is not None
