from __future__ import annotations

from typing import Optional


def team_totals(team_cars: dict[int, list[int]],
                car_points: dict[int, int]) -> dict[int, int]:
    totals: dict[int, int] = {}
    for team_id, car_ids in team_cars.items():
        s = sum(car_points.get(c, 0) for c in car_ids)
        if len(car_ids) == 1:        # 1 车队伍积分翻倍
            s *= 2
        totals[team_id] = s
    return totals


def team_winner(totals: dict[int, int]) -> Optional[int]:
    if len(totals) != 2:
        return max(totals, key=totals.get) if totals else None
    (ta, sa), (tb, sb) = totals.items()
    if sa == sb:
        return None                  # 并列 → 需加赛
    return ta if sa > sb else tb
