from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

_POINTS = {1: 5, 2: 3, 3: 2, 4: 1}


def points_for_rank(rank: Optional[int]) -> int:
    if rank is None:
        return 0
    return _POINTS.get(rank, 0)


def group_totals(results: dict[int, list[Optional[int]]]) -> dict[int, int]:
    return {car: sum(points_for_rank(r) for r in ranks)
            for car, ranks in results.items()}


@dataclass
class Advancement:
    advancers: Optional[list[int]]      # 已确定的两名晋级者(无歧义时)
    guaranteed: list[int]               # 无争议直接晋级者
    tie_between: Optional[list[int]]     # 需 1V1 的并列者(争夺最后晋级名额)


def resolve_advancement(totals: dict[int, int]) -> Advancement:
    """前 2 晋级;若第 2/3 名总分并列,返回需 1V1 的并列者。"""
    ordered = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    if len(ordered) <= 2:
        return Advancement(advancers=[c for c, _ in ordered], guaranteed=[c for c, _ in ordered], tie_between=None)
    second_score = ordered[1][1]
    third_score = ordered[2][1]
    if second_score != third_score:
        return Advancement(advancers=[ordered[0][0], ordered[1][0]],
                           guaranteed=[ordered[0][0], ordered[1][0]], tie_between=None)
    # 并列:找出所有等于 second_score 的车作为并列者;高于它的直接晋级
    guaranteed = [c for c, s in ordered if s > second_score]
    tied = [c for c, s in ordered if s == second_score]
    return Advancement(advancers=None, guaranteed=guaranteed, tie_between=tied)


def final_ranking(totals: dict[int, int]) -> list[int]:
    return [c for c, _ in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)]
