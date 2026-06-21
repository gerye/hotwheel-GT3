from app.models import TeamPointEntry


def test_team_point_entry_table(session):
    from app.services import seasons as ssvc
    s = ssvc.start_season(session, name="2026 S1")
    e = TeamPointEntry(season_id=s.id, team_id=1, points=5, description="测试")
    session.add(e); session.commit(); session.refresh(e)
    assert e.id is not None and e.points == 5
