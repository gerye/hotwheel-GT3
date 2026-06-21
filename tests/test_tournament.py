from app.models import Race, RaceRound, Group, Heat, HeatResult
from app.enums import Category, ProLevel, RaceFormat


def test_race_tables_exist(session):
    from app.services import seasons as ssvc
    s = ssvc.start_season(session, name="2026 S1")
    r = Race(season_id=s.id, category=Category.GT3,
             pro_level=ProLevel.PRO, format=RaceFormat.SOLO)
    session.add(r); session.commit(); session.refresh(r)
    assert r.id is not None and r.status.value == "进行中"
