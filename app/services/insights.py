from __future__ import annotations

from typing import Optional
from sqlmodel import Session, select
from app.models import (Car, Team, Season, Race, RaceRound, Group, Heat, HeatResult,
                        MarketDraft)
from app.enums import (Category, CarStatus, TeamType, RaceStatus, ACTIVE_STATUSES)
from app.config import (NUM_LANES, MAX_CARS_PER_CATEGORY,
                        LANE_MIN_SAMPLE, LANE_BIAS_THRESHOLD)
from app.services import teams as tsvc


def lane_stats(session: Session, *, season_id: Optional[int] = None,
               category: Optional[Category] = None) -> dict:
    """按车道汇总已结束比赛的 HeatResult。平均名次只算完赛;脱轨率/拿第一比例按出场数。"""
    stmt = (select(HeatResult)
            .join(Heat, HeatResult.heat_id == Heat.id)
            .join(Group, Heat.group_id == Group.id)
            .join(RaceRound, Group.round_id == RaceRound.id)
            .join(Race, RaceRound.race_id == Race.id)
            .where(Race.status == RaceStatus.FINISHED))
    if season_id is not None:
        stmt = stmt.where(Race.season_id == season_id)
    if category is not None:
        stmt = stmt.where(Race.category == category)
    results = session.exec(stmt).all()

    lanes = []
    for lane in range(1, NUM_LANES + 1):
        rows = [r for r in results if r.lane == lane]
        n = len(rows)
        finished = [r for r in rows if not r.dnf and r.rank is not None]
        dnf_n = sum(1 for r in rows if r.dnf)
        win_n = sum(1 for r in rows if r.rank == 1 and not r.dnf)
        avg_rank = (sum(r.rank for r in finished) / len(finished)) if finished else None
        lanes.append({
            "lane": lane, "n": n, "avg_rank": avg_rank,
            "dnf_rate": (dnf_n / n) if n else 0.0,
            "win_rate": (win_n / n) if n else 0.0,
            "low_sample": n < LANE_MIN_SAMPLE,
        })

    ranked = [l for l in lanes if l["avg_rank"] is not None and l["n"] >= LANE_MIN_SAMPLE]
    if len(ranked) >= 2:
        fastest = min(ranked, key=lambda l: l["avg_rank"])
        slowest = max(ranked, key=lambda l: l["avg_rank"])
        spread = slowest["avg_rank"] - fastest["avg_rank"]
        verdict = {"biased": spread >= LANE_BIAS_THRESHOLD, "spread": spread,
                   "fastest_lane": fastest["lane"], "slowest_lane": slowest["lane"],
                   "enough_sample": True}
    else:
        verdict = {"biased": None, "spread": None, "fastest_lane": None,
                   "slowest_lane": None, "enough_sample": False}
    return {"lanes": lanes, "total_results": len(results), "verdict": verdict}
