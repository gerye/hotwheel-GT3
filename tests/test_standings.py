from app.models import TeamPointEntry


def test_team_point_entry_table(session):
    from app.services import seasons as ssvc
    s = ssvc.start_season(session, name="2026 S1")
    e = TeamPointEntry(season_id=s.id, team_id=1, points=5, description="测试")
    session.add(e); session.commit(); session.refresh(e)
    assert e.id is not None and e.points == 5


from app.enums import Category, TeamType
from app.services import seasons as ssvc, cars as csvc, teams as tsvc, standings as st
from sqlmodel import select


def test_award_solo_points_to_car_teams(session):
    s = ssvc.start_season(session, name="2026 S1")
    t1 = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    t2 = tsvc.create_team(session, type=TeamType.FACTORY, brand="保时捷", name=None)
    c1 = csvc.create_car(session, nickname="法1", category=Category.GT3,
                         brand="法拉利", casting="", description="", team_id=t1.id)
    c2 = csvc.create_car(session, nickname="保1", category=Category.GT3,
                         brand="保时捷", casting="", description="", team_id=t2.id)
    c3 = csvc.create_car(session, nickname="无队", category=Category.GT3,
                         brand="奥迪", casting="", description="", team_id=None)
    st.award_solo(session, season_id=s.id, race_id=1, ranking=[c1.id, c2.id, c3.id])
    assert st.team_season_points(session, t1.id, s.id) == 5
    assert st.team_season_points(session, t2.id, s.id) == 4
    # 第三名无车队 → 无记录
    entries = session.exec(select(st.TeamPointEntry)).all()
    assert len(entries) == 2


def test_award_team_points(session):
    s = ssvc.start_season(session, name="2026 S1")
    t1 = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    t2 = tsvc.create_team(session, type=TeamType.FACTORY, brand="保时捷", name=None)
    st.award_team(session, season_id=s.id, race_id=1, ranking=[t1.id, t2.id])
    assert st.team_season_points(session, t1.id, s.id) == 10
    assert st.team_season_points(session, t2.id, s.id) == 8


def test_points_are_season_scoped(session):
    s1 = ssvc.start_season(session, name="2026 S1")
    t1 = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    st.award_team(session, season_id=s1.id, race_id=1, ranking=[t1.id])
    ssvc.end_season(session, s1.id)
    s2 = ssvc.start_season(session, name="2026 S2")
    assert st.team_season_points(session, t1.id, s2.id) == 0   # 新赛季清零
    assert st.team_season_points(session, t1.id, s1.id) == 10  # 旧赛季仍在


def test_standings_board_sorted(session):
    s = ssvc.start_season(session, name="2026 S1")
    t1 = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    t2 = tsvc.create_team(session, type=TeamType.FACTORY, brand="保时捷", name=None)
    st.award_team(session, season_id=s.id, race_id=1, ranking=[t2.id, t1.id])
    board = st.team_board(session, s.id)
    assert board[0][0].id == t2.id and board[0][1] == 10
