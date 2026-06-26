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
    assert res.advancers is None          # 需裁决
    assert set(res.tie_between) == {20, 30}
    assert res.guaranteed == [10]
    assert res.slots == 1                 # 只争第 2 一个名额


def test_advancement_three_way_tie_for_two_slots():
    # 第 1 名也并列 → 空出 2 个名额,需从三车里选 2
    totals = {10: 10, 20: 10, 30: 10, 40: 2}
    res = sc.resolve_advancement(totals)
    assert res.advancers is None
    assert res.guaranteed == []
    assert set(res.tie_between) == {10, 20, 30}
    assert res.slots == 2


def test_advancement_tie_count_equals_slots_all_advance():
    # 两车并列且正好 2 个名额(无人在其之上)→ 直接全晋级,无需裁决
    totals = {10: 10, 20: 10, 30: 4}
    res = sc.resolve_advancement(totals)
    assert set(res.advancers) == {10, 20}
    assert res.tie_between is None


def test_final_ranking_orders_by_total():
    totals = {10: 18, 20: 14, 30: 8, 40: 6}
    assert sc.final_ranking(totals) == [10, 20, 30, 40]
