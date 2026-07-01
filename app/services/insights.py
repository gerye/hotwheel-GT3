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


def overview_counts(session: Session) -> dict:
    cars = session.exec(select(Car)).all()
    return {
        "cars": len(cars),
        "teams": len(session.exec(select(Team)).all()),
        "active": sum(1 for c in cars if c.status in ACTIVE_STATUSES),
        "retired": sum(1 for c in cars if c.status == CarStatus.RETIRED),
        "unsigned": sum(1 for c in cars if c.status == CarStatus.UNSIGNED),
        "seasons": len(session.exec(select(Season)).all()),
    }


def health_checks(session: Session) -> list:
    checks = []

    # 1 状态一致性:无车队⟺未签约
    items = []
    for c in session.exec(select(Car)).all():
        has_team = c.team_id is not None
        if has_team and c.status == CarStatus.UNSIGNED:
            items.append({"label": f"{c.nickname}:有车队却「未签约」", "href": f"/cars/{c.id}"})
        elif not has_team and c.status != CarStatus.UNSIGNED:
            items.append({"label": f"{c.nickname}:无车队却「{c.status.value}」", "href": f"/cars/{c.id}"})
    checks.append({"key": "status_consistency", "title": "状态一致性(无车队 ⟺ 未签约)",
                   "severity": "error", "ok": not items, "items": items})

    # 2 名额超限
    items = []
    for t in session.exec(select(Team)).all():
        for cat in Category:
            n = tsvc.active_count(session, t.id, cat, None)
            if n > MAX_CARS_PER_CATEGORY:
                items.append({"label": f"{t.name} / {cat.value}:现役 {n} > {MAX_CARS_PER_CATEGORY}",
                              "href": f"/teams/{t.id}"})
    checks.append({"key": "capacity", "title": f"每类别现役 ≤ {MAX_CARS_PER_CATEGORY}",
                   "severity": "error", "ok": not items, "items": items})

    # 3 厂商品牌一致
    items = []
    for t in session.exec(select(Team).where(Team.type == TeamType.FACTORY)).all():
        for c in session.exec(select(Car).where(
                Car.team_id == t.id, Car.status.in_(ACTIVE_STATUSES))).all():
            if not tsvc.is_brandless(c.brand) and c.brand != t.brand:
                items.append({"label": f"{c.nickname}(品牌「{c.brand}」)在厂商队「{t.name}」(品牌「{t.brand}」)",
                              "href": f"/cars/{c.id}"})
    checks.append({"key": "brand_mismatch", "title": "厂商车队成员品牌一致",
                   "severity": "error", "ok": not items, "items": items})

    # 4 进行中未结束比赛(提醒)
    items = []
    for r in session.exec(select(Race).where(Race.status == RaceStatus.IN_PROGRESS)).all():
        items.append({"label": f"比赛 #{r.id} {r.category.value} 进行中未结束", "href": f"/races/{r.id}"})
    checks.append({"key": "unfinished_races", "title": "无进行中未结束的比赛",
                   "severity": "warn", "ok": not items, "items": items})

    # 5 残留转会草稿(提醒)
    items = []
    if session.exec(select(MarketDraft)).first() is not None:
        items.append({"label": "存在未定档的转会草稿(转会开着盘)", "href": "/market"})
    checks.append({"key": "open_draft", "title": "无残留转会草稿",
                   "severity": "warn", "ok": not items, "items": items})

    return checks
