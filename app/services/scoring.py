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
    advancers: Optional[list[int]]      # 已确定的晋级者(无歧义/已裁决时)
    guaranteed: list[int]               # 无争议直接晋级者
    tie_between: Optional[list[int]]     # 需人工裁决的并列者
    slots: int = 0                      # 需从并列者中选出几名晋级(空出的名额数)


def resolve_advancement(totals: dict[int, int]) -> Advancement:
    """前 2 晋级;若名额边界出现并列,返回并列者及待选名额数 slots。

    一般只需在并列者中选 1 名(争第 2)。但当第 1 名也并列时(如三车同分),
    空出的名额为 2,需选 2 名 —— 由 slots 表示。
    """
    ordered = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    if len(ordered) <= 2:
        return Advancement(advancers=[c for c, _ in ordered], guaranteed=[c for c, _ in ordered], tie_between=None)
    second_score = ordered[1][1]
    third_score = ordered[2][1]
    if second_score != third_score:
        return Advancement(advancers=[ordered[0][0], ordered[1][0]],
                           guaranteed=[ordered[0][0], ordered[1][0]], tie_between=None)
    # 并列:高于边界分的直接晋级;等于边界分的并列争夺剩余名额
    guaranteed = [c for c, s in ordered if s > second_score]
    tied = [c for c, s in ordered if s == second_score]
    slots = 2 - len(guaranteed)
    if len(tied) <= slots:              # 并列人数不超过空位 → 全部晋级,无需裁决
        return Advancement(advancers=guaranteed + tied, guaranteed=guaranteed, tie_between=None)
    return Advancement(advancers=None, guaranteed=guaranteed, tie_between=tied, slots=slots)


def final_ranking(totals: dict[int, int]) -> list[int]:
    return [c for c, _ in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)]
