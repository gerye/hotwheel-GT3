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
