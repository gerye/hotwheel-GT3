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


def test_team_winner_rejects_non_two_team_totals():
    import pytest
    with pytest.raises(ValueError):
        ts.team_winner({1: 10, 2: 9, 3: 8})


from app.enums import Category, ProLevel, RaceFormat, TeamType
from app.services import tournament as T, seasons as ssvc, cars as csvc, teams as tsvc
from sqlmodel import select
from app.models import Group, GroupMember, RaceRound


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


def _play_to_finish(session, race_id):
    """随机录完每场并推进,直到 finished;返回最终 AdvanceResult。"""
    for _ in range(200):
        rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race_id)
                           .order_by(RaceRound.number.desc())).first()
        groups = session.exec(select(Group).where(Group.round_id == rnd.id)).all()
        for g in groups:
            members = [m.car_id for m in session.exec(select(GroupMember)
                       .where(GroupMember.group_id == g.id)).all()]
            for h in session.exec(select(Heat).where(Heat.group_id == g.id)).all():
                if not h.recorded:
                    T.record_heat(session, h.id,
                                  ranks={c: i + 1 for i, c in enumerate(members)})
        res = T.advance_round(session, race_id, seed=7)
        if res.kind == "finished":
            return res
        if res.kind == "needs_decision":
            gid = res.pending_group_ids[0]
            adv = T.settle_group(session, gid)
            need = max(0, 2 - len(adv.guaranteed or []))
            T.resolve_tie(session, gid, winner_car_ids=(adv.tie_between or [])[:need])
    raise AssertionError("200 轮未收敛")


def test_odd_team_bracket_finishes_with_bye(session):
    """回归:非 2 的幂车队数(6→3→2)靠轮空(bye)推进,不再崩溃。"""
    ssvc.start_season(session, name="2026 S1")
    teams = []
    for b in ["法拉利", "保时捷", "奥迪", "宝马", "迈凯伦", "阿斯顿"]:
        t, _ = _team_with_cars(session, b, 2)
        teams.append(t.id)
    race = T.create_team_race(session, category=Category.GT3,
                              pro_level=ProLevel.PRO, team_ids=teams, seed=3)
    # 6 队 → 3 对(首轮均衡)→ 3 队 → 1 对 + 1 轮空 → 2 队决赛
    res = _play_to_finish(session, race.id)
    assert res.kind == "finished"
    assert len(res.ranking) >= 1
    # 过程中出现过轮空组(team_b 为空但 team_a 有值)
    rounds = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).all()
    all_groups = session.exec(select(Group).where(
        Group.round_id.in_([r.id for r in rounds]))).all()
    byes = [g for g in all_groups if g.team_b_id is None and g.team_a_id is not None]
    assert byes, "3 队轮次应产生一个轮空组"


def test_replay_adds_four_heats(session):
    ssvc.start_season(session, name="2026 S1")
    t1, c1 = _team_with_cars(session, "法拉利", 2)
    t2, c2 = _team_with_cars(session, "保时捷", 2)
    race = T.create_team_race(session, category=Category.GT3,
                              pro_level=ProLevel.PRO, team_ids=[t1.id, t2.id], seed=1)
    grp = session.exec(select(Group)).first()
    before = len(session.exec(select(Heat).where(Heat.group_id == grp.id)).all())
    T.extend_team_group_with_replay(session, grp.id)
    after = len(session.exec(select(Heat).where(Heat.group_id == grp.id)).all())
    assert after == before + 4
