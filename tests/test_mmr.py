import pytest
from app.services import mmr


def test_equal_ratings_winner_gains_loser_loses_symmetric():
    # 两车同分 1500,car 10 赢 car 20
    ratings = {10: 1500.0, 20: 1500.0}
    totals = {10: 10, 20: 6}
    d = mmr.elo_deltas(ratings, totals, k=24)
    assert round(d[10], 2) == 12.0
    assert round(d[20], 2) == -12.0


def test_zero_sum_in_group_of_four():
    ratings = {10: 1500.0, 20: 1500.0, 30: 1500.0, 40: 1500.0}
    totals = {10: 18, 20: 14, 30: 8, 40: 6}
    d = mmr.elo_deltas(ratings, totals, k=24)
    assert round(sum(d.values()), 6) == 0.0
    assert d[10] > 0 and d[40] < 0


def test_upset_gives_more_points():
    # 1400 赢 1600
    ratings = {10: 1400.0, 20: 1600.0}
    totals = {10: 10, 20: 6}
    d = mmr.elo_deltas(ratings, totals, k=24)
    assert d[10] > 12          # 爆冷涨更多
    assert round(d[10], 2) == 18.23
    assert round(d[20], 2) == -18.23


def test_tie_counts_as_half():
    ratings = {10: 1500.0, 20: 1500.0}
    totals = {10: 8, 20: 8}    # 同分=平
    d = mmr.elo_deltas(ratings, totals, k=24)
    assert round(d[10], 2) == 0.0 and round(d[20], 2) == 0.0


from sqlmodel import select
from app.models import Car, Group, GroupMember, Heat
from app.enums import Category, ProLevel, RaceFormat
from app.services import seasons as ssvc, cars as csvc, tournament as T


def _solo_group_recorded(session):
    """建一个 4 车专业单人赛,按成员顺序录入名次,返回 (group, members)。"""
    from app.models import Team
    from app.enums import TeamType
    ssvc.start_season(session, name="2026 S1")
    ids = []
    for i in range(4):
        team = Team(type=TeamType.INDEPENDENT, name=f"MMR测试车队{i}")
        session.add(team); session.commit(); session.refresh(team)
        c = csvc.create_car(session, nickname=f"车{i}", category=Category.GT3,
                            brand="法拉利", casting="", description="",
                            team_id=team.id)
        ids.append(c.id)
    T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                  format=RaceFormat.SOLO, car_ids=ids, seed=1)
    grp = session.exec(select(Group)).first()
    members = [m.car_id for m in session.exec(
        select(GroupMember).where(GroupMember.group_id == grp.id)).all()]
    for h in session.exec(select(Heat).where(Heat.group_id == grp.id)).all():
        T.record_heat(session, h.id,
                      ranks={c: i + 1 for i, c in enumerate(members)})
    return grp, members


def test_settle_group_mmr_updates_both_ladders(session):
    grp, members = _solo_group_recorded(session)
    mmr.settle_group_mmr(session, grp.id)
    winner = session.get(Car, members[0])
    loser = session.get(Car, members[-1])
    assert winner.season_mmr > 1500 and winner.historical_mmr > 1500
    assert loser.season_mmr < 1500 and loser.historical_mmr < 1500
    session.refresh(grp)
    assert grp.mmr_settled is True


def test_settle_group_mmr_idempotent(session):
    grp, members = _solo_group_recorded(session)
    mmr.settle_group_mmr(session, grp.id)
    first = session.get(Car, members[0]).season_mmr
    mmr.settle_group_mmr(session, grp.id)   # 再次调用不应重复加分
    assert session.get(Car, members[0]).season_mmr == first
