from __future__ import annotations

from app.config import ELO_K


def _expected(my: float, opp: float) -> float:
    return 1.0 / (1.0 + 10 ** ((opp - my) / 400.0))


def elo_deltas(ratings: dict[int, float], totals: dict[int, int],
               k: float = ELO_K) -> dict[int, float]:
    """按小组总分两两对战,返回每辆车的 MMR 变化(零和)。"""
    cars = list(ratings.keys())
    deltas: dict[int, float] = {c: 0.0 for c in cars}
    for i, a in enumerate(cars):
        for b in cars[i + 1:]:
            if totals[a] > totals[b]:
                sa = 1.0
            elif totals[a] < totals[b]:
                sa = 0.0
            else:
                sa = 0.5
            ea = _expected(ratings[a], ratings[b])
            change = k * (sa - ea)        # a 视角的变化
            deltas[a] += change
            deltas[b] -= change           # 零和:b 得到相反值
    return deltas


def apply_deltas(ratings: dict[int, float],
                 deltas: dict[int, float]) -> dict[int, float]:
    return {c: ratings[c] + deltas.get(c, 0.0) for c in ratings}
