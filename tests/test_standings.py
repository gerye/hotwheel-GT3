from app.models import TeamPointEntry


def test_team_point_entry_table(session):
    from app.services import seasons as ssvc
    s = ssvc.start_season(session, name="2026 S1")
    e = TeamPointEntry(season_id=s.id, team_id=1, points=5, description="测试")
    session.add(e); session.commit(); session.refresh(e)
    assert e.id is not None and e.points == 5


from app.enums import Category, ProLevel, RaceFormat, TeamType
from app.services import (seasons as ssvc, cars as csvc, teams as tsvc,
                          standings as st, tournament as T)
from app.models import Race, RaceRound, Group, GroupMember, Heat, TeamPointEntry
from sqlmodel import select


def _run_solo_final(session, season, n=4):
    """跑一场 n 车单人赛直到结束(n<=4 时无晋级,1 轮即决赛组)。"""
    teams, ids = [], []
    for i in range(n):
        t = tsvc.create_team(session, type=TeamType.FACTORY,
                             brand="法拉利" if i % 2 == 0 else "保时捷", name=None)
        teams.append(t)
        ids.append(csvc.create_car(session, nickname=f"c{i}", category=Category.GT3,
                   brand=t.brand, casting="", description="", team_id=t.id).id)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=ids, seed=1)
    rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).first()
    grp = session.exec(select(Group).where(Group.round_id == rnd.id)).first()
    members = [m.car_id for m in session.exec(select(GroupMember)
               .where(GroupMember.group_id == grp.id)).all()]
    for h in session.exec(select(Heat).where(Heat.group_id == grp.id)).all():
        T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(members)})
    result = T.advance_round(session, race.id)
    return teams, ids, result


def test_award_solo_points_to_car_teams(session):
    s = ssvc.start_season(session, name="2026 S1")
    teams, ids, result = _run_solo_final(session, s)
    assert result.kind == "finished"
    # 4 车决赛组、单一轮无晋级:冠军 +4,亚军 +2,第3 +1,第4 +0
    Car = __import__("app.models", fromlist=["Car"]).Car
    champ_team_id = session.get(Car, result.ranking[0]).team_id
    second_team_id = session.get(Car, result.ranking[1]).team_id
    assert st.team_season_points(session, champ_team_id, s.id) == 4
    assert st.team_season_points(session, second_team_id, s.id) == 2


def test_award_team_points(session):
    s = ssvc.start_season(session, name="2026 S1")
    teams, ids, result = _run_solo_final(session, s)
    assert result.kind == "finished"
    Car = __import__("app.models", fromlist=["Car"]).Car
    champ_team_id = session.get(Car, result.ranking[0]).team_id
    third_team_id = session.get(Car, result.ranking[2]).team_id
    # 单人赛无 ×2 倍率:冠军 +4,第三名 +1
    assert st.team_season_points(session, champ_team_id, s.id) == 4
    assert st.team_season_points(session, third_team_id, s.id) == 1


def test_points_are_season_scoped(session):
    s1 = ssvc.start_season(session, name="2026 S1")
    t1 = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    session.add(TeamPointEntry(season_id=s1.id, team_id=t1.id, points=10, description="测试"))
    session.commit()
    ssvc.end_season(session, s1.id)
    s2 = ssvc.start_season(session, name="2026 S2")
    assert st.team_season_points(session, t1.id, s2.id) == 0   # 新赛季清零
    assert st.team_season_points(session, t1.id, s1.id) == 10  # 旧赛季仍在


def test_standings_board_sorted(session):
    s = ssvc.start_season(session, name="2026 S1")
    t1 = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    t2 = tsvc.create_team(session, type=TeamType.FACTORY, brand="保时捷", name=None)
    session.add(TeamPointEntry(season_id=s.id, team_id=t1.id, points=5, description="测试"))
    session.add(TeamPointEntry(season_id=s.id, team_id=t2.id, points=10, description="测试"))
    session.commit()
    board = st.team_board(session, s.id)
    assert board[0][0].id == t2.id and board[0][1] == 10


from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_standings_page_shows_mmr_and_team_board(engine, session):
    s = ssvc.start_season(session, name="2026 S1")
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    c = csvc.create_car(session, nickname="法1", category=Category.GT3,
                        brand="法拉利", casting="", description="", team_id=t.id)
    session.add(TeamPointEntry(season_id=s.id, team_id=t.id, points=10, description="测试"))
    session.commit()
    r = client.get("/standings")
    assert r.status_code == 200
    assert "法1" in r.text and "法拉利车队" in r.text


def test_standings_mmr_filtered_by_category(engine, session):
    ssvc.start_season(session, name="2026 S1")
    csvc.create_car(session, nickname="GT3车", category=Category.GT3,
                    brand="法拉利", casting="", description="", team_id=None)
    csvc.create_car(session, nickname="F1车", category=Category.F1,
                    brand="法拉利", casting="", description="", team_id=None)
    r = client.get("/standings?category=GT3")
    assert "GT3车" in r.text and "F1车" not in r.text
