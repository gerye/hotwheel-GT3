from app.services import team_scoring as ts


def test_team_total_simple():
    # team_cars: team_id -> [car_ids];car_points: car -> 总分
    team_cars = {1: [10, 11], 2: [20, 21]}
    car_points = {10: 8, 11: 6, 20: 5, 21: 4}
    totals = ts.team_totals(team_cars, car_points)
    assert totals == {1: 14, 2: 9}


def test_single_car_team_doubled():
    team_cars = {1: [10], 2: [20, 21]}
    car_points = {10: 8, 20: 5, 21: 4}
    totals = ts.team_totals(team_cars, car_points)
    assert totals[1] == 16          # 8 * 2
    assert totals[2] == 9


def test_team_winner_no_tie():
    assert ts.team_winner({1: 16, 2: 9}) == 1


def test_team_tie_returns_none():
    assert ts.team_winner({1: 10, 2: 10}) is None


from app.enums import Category, ProLevel, RaceFormat, TeamType
from app.services import tournament as T, seasons as ssvc, cars as csvc, teams as tsvc
from sqlmodel import select
from app.models import Group, GroupMember


def _team_with_cars(session, brand, n):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand=brand, name=None)
    ids = []
    for i in range(n):
        c = csvc.create_car(session, nickname=f"{brand}{i}", category=Category.GT3,
                            brand=brand, casting="", description="", team_id=t.id)
        ids.append(c.id)
    return t, ids


def test_team_race_groups_two_teams_each(session):
    ssvc.start_season(session, name="2026 S1")
    teams = []
    car_ids = []
    for b in ["法拉利", "保时捷", "奥迪", "宝马"]:
        t, ids = _team_with_cars(session, b, 2)
        teams.append(t.id); car_ids += ids
    race = T.create_team_race(session, category=Category.GT3,
                              pro_level=ProLevel.PRO, team_ids=teams, seed=1)
    grp = session.exec(select(Group)).first()
    assert grp.team_a_id is not None and grp.team_b_id is not None
    members = session.exec(select(GroupMember)
                           .where(GroupMember.group_id == grp.id)).all()
    assert len(members) == 4          # 两队各 2 车


from app.models import Heat, HeatResult


def test_team_group_settle_picks_winner_team(session):
    ssvc.start_season(session, name="2026 S1")
    t1, c1 = _team_with_cars(session, "法拉利", 2)
    t2, c2 = _team_with_cars(session, "保时捷", 2)
    race = T.create_team_race(session, category=Category.GT3,
                              pro_level=ProLevel.PRO, team_ids=[t1.id, t2.id], seed=1)
    grp = session.exec(select(Group)).first()
    members = [m.car_id for m in session.exec(select(GroupMember)
               .where(GroupMember.group_id == grp.id)).all()]
    # 让法拉利两车包揽前二
    fer = set(c1)
    for h in session.exec(select(Heat).where(Heat.group_id == grp.id)).all():
        ordered = [c for c in members if c in fer] + [c for c in members if c not in fer]
        T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(ordered)})
    winner = T.settle_team_group(session, grp.id)
    assert winner.winner_team_id == t1.id
