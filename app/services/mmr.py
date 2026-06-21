from __future__ import annotations

from sqlmodel import Session, select

from app.config import ELO_K
from app.models import Car, Group, Heat, HeatResult
from app.services import scoring


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


def _group_totals(session: Session, group_id: int) -> dict[int, int]:
    results: dict[int, list] = {}
    for h in session.exec(select(Heat).where(Heat.group_id == group_id)).all():
        for r in session.exec(select(HeatResult)
                              .where(HeatResult.heat_id == h.id)).all():
            results.setdefault(r.car_id, []).append(r.rank)
    return scoring.group_totals(results)


def settle_group_mmr(session: Session, group_id: int) -> None:
    group = session.get(Group, group_id)
    if group.mmr_settled:
        return
    totals = _group_totals(session, group_id)
    cars = {cid: session.get(Car, cid) for cid in totals}
    season_ratings = {cid: c.season_mmr for cid, c in cars.items()}
    hist_ratings = {cid: c.historical_mmr for cid, c in cars.items()}
    season_d = elo_deltas(season_ratings, totals)
    hist_d = elo_deltas(hist_ratings, totals)
    for cid, c in cars.items():
        c.season_mmr += season_d[cid]
        c.historical_mmr += hist_d[cid]
        session.add(c)
    group.mmr_settled = True
    session.add(group)
    session.commit()
