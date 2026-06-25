from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional
from sqlmodel import Session, select
from app.models import (Race, RaceEntry, RaceRound, Group, GroupMember,
                        Heat, HeatResult, Car, Team, TieBreak)
from app.enums import Category, ProLevel, RaceFormat, RaceStatus
from app.services import grouping, lineup, seasons as ssvc
from app.services import mmr as mmr_svc, standings as st_svc
from app.services import scoring, team_scoring


def create_race(session: Session, *, category: Category, pro_level: ProLevel,
                format: RaceFormat, car_ids: list[int],
                seed: Optional[int] = None) -> Race:
    season = ssvc.get_active_season(session)
    if season is None:
        raise ValueError("没有进行中的赛季,请先开启赛季")
    if pro_level == ProLevel.PRO:
        from app.enums import CarStatus
        for cid in car_ids:
            car = session.get(Car, cid)
            if car is not None and car.status != CarStatus.ACTIVE:
                raise ValueError("专业赛只能选择现役赛车")
    grouping.group_sizes(len(car_ids))   # 提前校验数量,非法直接抛 GroupingError
    race = Race(season_id=season.id, category=category, pro_level=pro_level,
                format=format, status=RaceStatus.IN_PROGRESS)
    session.add(race); session.commit(); session.refresh(race)
    for cid in car_ids:
        session.add(RaceEntry(race_id=race.id, car_id=cid))
    session.commit()
    _build_round(session, race, number=1, car_ids=car_ids, seed=seed)
    return race


def _build_round(session: Session, race: Race, *, number: int,
                 car_ids: list[int], seed: Optional[int]) -> RaceRound:
    is_final = len(car_ids) <= 4
    rnd = RaceRound(race_id=race.id, number=number, is_final=is_final)
    session.add(rnd); session.commit(); session.refresh(rnd)
    planned = grouping.partition(car_ids, seed=seed)
    for pg in planned:
        group = Group(round_id=rnd.id, label=pg.label)
        session.add(group); session.commit(); session.refresh(group)
        for cid in pg.members:
            session.add(GroupMember(group_id=group.id, car_id=cid))
        session.commit()
        _build_heats(session, group, pg.members)
    return rnd


def _build_heats(session: Session, group: Group, members: list[int]) -> None:
    schedule = lineup.build_lineup(members)   # 4 场 × 4 道
    for hi, lane_to_car in enumerate(schedule, start=1):
        heat = Heat(group_id=group.id, number=hi, recorded=False)
        session.add(heat); session.commit(); session.refresh(heat)
        for lane_idx, car in enumerate(lane_to_car, start=1):
            if car is not None:
                session.add(HeatResult(heat_id=heat.id, car_id=car,
                                       lane=lane_idx, rank=None))
        session.commit()


class HeatInputError(Exception):
    """单场结果录入非法。"""


def _validate_heat_input(car_ids: set[int], ranks: dict[int, int],
                         dnf: set[int]) -> None:
    for cid in car_ids:
        has_rank = ranks.get(cid) is not None
        is_dnf = cid in dnf
        if has_rank and is_dnf:
            raise HeatInputError("同一辆车不能既填名次又勾「未完赛」,请修正后重新录入。")
        if not has_rank and not is_dnf:
            raise HeatInputError("每辆车都要填名次或勾「未完赛」,请补全后重新录入。")
    finishers = [cid for cid in car_ids
                 if cid not in dnf and ranks.get(cid) is not None]
    given = sorted(ranks[cid] for cid in finishers)
    if given != list(range(1, len(finishers) + 1)):
        raise HeatInputError("名次必须是 1、2、3… 连续且不重复(不能并列或缺号),请重新录入。")


def record_heat(session: Session, heat_id: int, *,
                ranks: dict[int, int], dnf: set[int] | None = None) -> None:
    dnf = dnf or set()
    heat = session.get(Heat, heat_id)
    rows = session.exec(select(HeatResult).where(HeatResult.heat_id == heat_id)).all()
    _validate_heat_input({r.car_id for r in rows}, ranks, dnf)
    for r in rows:
        if r.car_id in dnf:
            r.rank = None
            r.dnf = True
        else:
            r.rank = ranks.get(r.car_id)
            r.dnf = False
        session.add(r)
    heat.recorded = True
    session.add(heat)
    session.commit()


def undo_heat(session: Session, heat_id: int) -> None:
    heat = session.get(Heat, heat_id)
    rows = session.exec(select(HeatResult).where(HeatResult.heat_id == heat_id)).all()
    for r in rows:
        r.rank = None
        r.dnf = False
        session.add(r)
    heat.recorded = False
    session.add(heat)
    group = session.get(Group, heat.group_id)
    group.mmr_settled = False
    session.add(group)
    session.commit()


def group_scoreboard(session: Session, group: Group, race: Race) -> dict:
    """小组实时积分榜:每车每场得分 + 总分;车队赛按车队总分聚合。"""
    heats = session.exec(select(Heat).where(Heat.group_id == group.id)
                         .order_by(Heat.number)).all()
    n = len(heats)
    names = {c.id: c.nickname for c in session.exec(select(Car)).all()}
    per_car: dict[int, list] = {}
    for idx, h in enumerate(heats):
        for r in session.exec(select(HeatResult)
                              .where(HeatResult.heat_id == h.id)).all():
            per_car.setdefault(r.car_id, [0] * n)
            per_car[r.car_id][idx] = scoring.points_for_rank(r.rank)
    car_total = {cid: sum(v) for cid, v in per_car.items()}

    def car_row(cid: int) -> dict:
        return {"name": names.get(cid, "?"), "heats": per_car[cid],
                "total": car_total[cid]}

    if race.format == RaceFormat.TEAM:
        entries = session.exec(select(RaceEntry)
                               .where(RaceEntry.race_id == race.id)).all()
        car_team = {e.car_id: e.team_id for e in entries if e.team_id is not None}
        team_cars: dict[int, list] = {}
        for cid in per_car:
            tid = car_team.get(cid)
            if tid is not None:
                team_cars.setdefault(tid, []).append(cid)
        totals = team_scoring.team_totals(team_cars, car_total)
        teams = []
        for tid in sorted(totals, key=lambda t: totals[t], reverse=True):
            tm = session.get(Team, tid)
            teams.append({
                "name": tm.specific_name(race.category) if tm else "?",
                "total": totals[tid],
                "cars": [car_row(cid) for cid in team_cars[tid]],
            })
        return {"is_team": True, "n_heats": n, "teams": teams}

    rows = sorted((car_row(cid) for cid in per_car),
                  key=lambda r: r["total"], reverse=True)
    return {"is_team": False, "n_heats": n, "rows": rows}


def _group_results(session: Session, group_id: int) -> dict[int, list]:
    results: dict[int, list] = {}
    heats = session.exec(select(Heat).where(Heat.group_id == group_id)).all()
    for h in heats:
        for r in session.exec(select(HeatResult)
                              .where(HeatResult.heat_id == h.id)).all():
            results.setdefault(r.car_id, []).append(r.rank)
    return results


def group_recorded(session: Session, group_id: int) -> bool:
    heats = session.exec(select(Heat).where(Heat.group_id == group_id)).all()
    return all(h.recorded for h in heats)


def settle_group(session: Session, group_id: int) -> scoring.Advancement:
    """返回晋级判定;若存在已裁决的 1V1,则把胜者并入晋级。"""
    totals = scoring.group_totals(_group_results(session, group_id))
    adv = scoring.resolve_advancement(totals)
    if adv.tie_between is not None:
        tb = session.exec(select(TieBreak)
                          .where(TieBreak.group_id == group_id)).first()
        if tb is not None and tb.winner_car_id is not None:
            adv = scoring.Advancement(
                advancers=adv.guaranteed + [tb.winner_car_id],
                guaranteed=adv.guaranteed, tie_between=None)
    return adv


def resolve_tie(session: Session, group_id: int, *, winner_car_id: int) -> None:
    tb = session.exec(select(TieBreak).where(TieBreak.group_id == group_id)).first()
    if tb is None:
        tb = TieBreak(group_id=group_id)
    tb.winner_car_id = winner_car_id
    session.add(tb); session.commit()


def _round_groups(session: Session, round_id: int) -> list[Group]:
    return session.exec(select(Group).where(Group.round_id == round_id)).all()


@dataclass
class AdvanceResult:
    kind: str                       # "needs_decision" | "needs_results" | "next_round" | "finished"
    ranking: list[int] | None = None
    pending_group_ids: list[int] | None = None


def advance_round(session: Session, race_id: int,
                  seed: Optional[int] = None) -> AdvanceResult:
    race = session.get(Race, race_id)
    if race.status == RaceStatus.FINISHED:
        rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race_id)
                           .order_by(RaceRound.number.desc())).first()
        groups = _round_groups(session, rnd.id)
        totals = scoring.group_totals(_group_results(session, groups[0].id))
        return AdvanceResult(kind="finished", ranking=scoring.final_ranking(totals))
    rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race_id)
                       .order_by(RaceRound.number.desc())).first()
    groups = _round_groups(session, rnd.id)

    # 1) 所有小组必须录完
    not_done = [g.id for g in groups if not group_recorded(session, g.id)]
    if not_done:
        return AdvanceResult(kind="needs_results", pending_group_ids=not_done)

    # 专业赛:本轮每组结算一次 MMR(幂等)
    if race.pro_level == ProLevel.PRO:
        for g in groups:
            mmr_svc.settle_group_mmr(session, g.id)

    # 2) 决赛轮:输出最终名次并结束
    if rnd.is_final:
        # 车队决赛并列 → 加赛 4 轮,先不结束
        if race.format == RaceFormat.TEAM:
            if settle_team_group(session, groups[0].id).winner_team_id is None:
                extend_team_group_with_replay(session, groups[0].id)
                return AdvanceResult(kind="needs_results",
                                     pending_group_ids=[groups[0].id])
        totals = scoring.group_totals(_group_results(session, groups[0].id))
        ranking = scoring.final_ranking(totals)
        race.status = RaceStatus.FINISHED
        session.add(race); session.commit()
        if race.pro_level == ProLevel.PRO:
            st_svc.award_race(session, race)
        return AdvanceResult(kind="finished", ranking=ranking)

    # 3) 车队锦标赛:逐组比车队总分,胜队晋级;并列则加赛 4 轮
    if race.format == RaceFormat.TEAM:
        winners: list[int] = []
        for g in groups:
            res = settle_team_group(session, g.id)
            if res.winner_team_id is None:      # 车队总分并列 → 加赛
                extend_team_group_with_replay(session, g.id)
                return AdvanceResult(kind="needs_results", pending_group_ids=[g.id])
            winners.append(res.winner_team_id)
        _build_team_round(session, race, number=rnd.number + 1,
                          team_ids=winners, category=race.category, seed=seed)
        return AdvanceResult(kind="next_round")

    # 4) 单人锦标赛非决赛轮:逐组结算,遇未裁决并列则要求决断
    advancers: list[int] = []
    for g in groups:
        adv = settle_group(session, g.id)
        if adv.advancers is None:
            return AdvanceResult(kind="needs_decision", pending_group_ids=[g.id])
        advancers.extend(adv.advancers)

    # 5) 用晋级者建下一轮
    _build_round(session, race, number=rnd.number + 1, car_ids=advancers, seed=seed)
    return AdvanceResult(kind="next_round")


def _team_final_ranking(session: Session, race: Race, final_group: Group) -> list[int]:
    """车队赛决赛组(2 队)→ [胜队, 负队]。第 3 名留待细化(见 spec §8)。"""
    res = settle_team_group(session, final_group.id)
    a, b = final_group.team_a_id, final_group.team_b_id
    if res.winner_team_id == b:
        return [b, a]
    return [a, b]


def _team_cars(session: Session, team_id: int, category: Category) -> list[int]:
    from app.enums import CarStatus
    return [c.id for c in session.exec(select(Car).where(
        Car.team_id == team_id, Car.category == category,
        Car.status == CarStatus.ACTIVE)).all()]   # 只派现役车手出战


def create_team_race(session: Session, *, category: Category, pro_level: ProLevel,
                     team_ids: list[int], seed: Optional[int] = None) -> Race:
    season = ssvc.get_active_season(session)
    if season is None:
        raise ValueError("没有进行中的赛季,请先开启赛季")
    if len(team_ids) % 2 != 0:
        raise ValueError("车队锦标赛需要偶数支车队(每组 2 队)")
    race = Race(season_id=season.id, category=category, pro_level=pro_level,
                format=RaceFormat.TEAM, status=RaceStatus.IN_PROGRESS)
    session.add(race); session.commit(); session.refresh(race)
    for tid in team_ids:
        for cid in _team_cars(session, tid, category):
            session.add(RaceEntry(race_id=race.id, car_id=cid, team_id=tid))
    session.commit()
    _build_team_round(session, race, number=1, team_ids=team_ids,
                      category=category, seed=seed)
    return race


def _build_team_round(session: Session, race: Race, *, number: int,
                      team_ids: list[int], category: Category,
                      seed: Optional[int]) -> RaceRound:
    is_final = len(team_ids) <= 2
    rnd = RaceRound(race_id=race.id, number=number, is_final=is_final)
    session.add(rnd); session.commit(); session.refresh(rnd)
    pool = list(team_ids)
    random.Random(seed).shuffle(pool)
    pairs = [pool[i:i + 2] for i in range(0, len(pool), 2)]
    for idx, (ta, tb) in enumerate(pairs):
        group = Group(round_id=rnd.id, label=chr(ord("A") + idx),
                      team_a_id=ta, team_b_id=tb)
        session.add(group); session.commit(); session.refresh(group)
        members = _team_cars(session, ta, category) + _team_cars(session, tb, category)
        for cid in members:
            session.add(GroupMember(group_id=group.id, car_id=cid))
        session.commit()
        _build_heats(session, group, members)
    return rnd


@dataclass
class TeamGroupResult:
    winner_team_id: Optional[int]      # None 表示并列需加赛


def settle_team_group(session: Session, group_id: int) -> TeamGroupResult:
    group = session.get(Group, group_id)
    results = _group_results(session, group_id)
    car_points = scoring.group_totals(results)
    # 用本组成员归属拆出两队的车
    team_cars: dict[int, list[int]] = {group.team_a_id: [], group.team_b_id: []}
    for cid in car_points:
        entry = session.exec(select(RaceEntry).where(
            RaceEntry.car_id == cid, RaceEntry.team_id.in_(
                [group.team_a_id, group.team_b_id]))).first()
        if entry:
            team_cars[entry.team_id].append(cid)
    totals = team_scoring.team_totals(team_cars, car_points)
    winner = team_scoring.team_winner(totals)
    return TeamGroupResult(winner_team_id=winner)


def extend_team_group_with_replay(session: Session, group_id: int) -> None:
    members = [m.car_id for m in session.exec(select(GroupMember)
               .where(GroupMember.group_id == group_id)).all()]
    existing = session.exec(select(Heat).where(Heat.group_id == group_id)).all()
    start = max((h.number for h in existing), default=0)
    schedule = lineup.build_lineup(members)
    for i, lane_to_car in enumerate(schedule, start=start + 1):
        heat = Heat(group_id=group_id, number=i, recorded=False)
        session.add(heat); session.commit(); session.refresh(heat)
        for lane_idx, car in enumerate(lane_to_car, start=1):
            if car is not None:
                session.add(HeatResult(heat_id=heat.id, car_id=car,
                                       lane=lane_idx, rank=None))
        session.commit()
