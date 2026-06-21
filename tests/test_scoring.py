from __future__ import annotations

import pytest
from app.services import scoring as sc


def test_points_for_rank():
    assert sc.points_for_rank(1) == 5
    assert sc.points_for_rank(2) == 3
    assert sc.points_for_rank(3) == 2
    assert sc.points_for_rank(4) == 1
    assert sc.points_for_rank(None) == 0   # DNF


def test_group_totals():
    # car -> list of ranks across 4 heats
    results = {10: [1, 1, 2, 1], 20: [2, 2, 1, 2], 30: [3, 3, 3, None]}
    totals = sc.group_totals(results)
    assert totals[10] == 5 + 5 + 3 + 5
    assert totals[20] == 3 + 3 + 5 + 3
    assert totals[30] == 2 + 2 + 2 + 0


def test_advancers_top_two_no_tie():
    totals = {10: 18, 20: 14, 30: 8, 40: 6}
    res = sc.resolve_advancement(totals)
    assert res.advancers == [10, 20]
    assert res.tie_between is None


def test_advancement_tie_for_second():
    totals = {10: 18, 20: 10, 30: 10, 40: 6}
    res = sc.resolve_advancement(totals)
    assert res.advancers is None          # 需 1V1
    assert set(res.tie_between) == {20, 30}
    assert res.guaranteed == [10]


def test_final_ranking_orders_by_total():
    totals = {10: 18, 20: 14, 30: 8, 40: 6}
    assert sc.final_ranking(totals) == [10, 20, 30, 40]
