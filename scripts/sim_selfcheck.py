"""全链路自检模拟(离线,绝不碰真实库)。

在一个全新的**内存 SQLite** 上跑通整条链路,验证各机制自洽:
建库(10 车队 / 60 车,随机长期短期)→ 每级别 2 单人 + 2 车队专业赛(随机结果)
→ MMR 零和 / 车队积分 / 薪资 / 预算 → 赛季结束快照+重置 → 新选秀(逐队逐类别
+ 挖角 + 优先级重算 + 一键重置)。

用途:每次改动后一键回归整条链路(比单元测试更接近真实使用序列)。
运行:  `./.venv/bin/python -m scripts.sim_selfcheck`   或   `./.venv/bin/python scripts/sim_selfcheck.py`
退出码:发现问题 → 1;全部正常 → 0(便于接进 CI / pre-push)。

铁律:本脚本用 `db.set_engine(<内存引擎>)` 注入独立引擎,**不触碰 data/hotwheel.db**。
"""
from __future__ import annotations

import random
import sys

from sqlmodel import SQLModel, Session, create_engine, select
from sqlmodel.pool import StaticPool

import app.db as db
import app.models  # noqa: F401  确保模型注册
from app.models import (Car, Team, CarSeasonMMR, RaceRound, Group, GroupMember,
                        Heat, DraftCarSnapshot)
from app.enums import (Category, TeamType, CarStatus, ProLevel, RaceFormat,
                       ACTIVE_STATUSES)
from app.services import (seasons as ssvc, teams as tsvc, cars as csvc,
                          tournament as T, standings as st, salary as sal,
                          budget as bud, market, market_draft as md)

CATS = [Category.F1, Category.GT3, Category.ROAD]


def _play_race(s, race_id, rng):
    """随机录完每一场并推进,直到 finished;返回最终 AdvanceResult。"""
    for _ in range(300):
        rnd = s.exec(select(RaceRound).where(RaceRound.race_id == race_id)
                     .order_by(RaceRound.number.desc())).first()
        for g in s.exec(select(Group).where(Group.round_id == rnd.id)).all():
            members = [m.car_id for m in s.exec(select(GroupMember)
                       .where(GroupMember.group_id == g.id)).all()]
            for h in s.exec(select(Heat).where(Heat.group_id == g.id)).all():
                if not h.recorded and members:
                    order = rng.sample(members, len(members))
                    T.record_heat(s, h.id, ranks={c: i + 1 for i, c in enumerate(order)})
        res = T.advance_round(s, race_id, seed=rng.randint(0, 10 ** 6))
        if res.kind == "finished":
            return res
        if res.kind == "needs_decision":
            gid = res.pending_group_ids[0]
            adv = T.settle_group(s, gid)
            need = max(0, 2 - len(adv.guaranteed or []))
            T.resolve_tie(s, gid, winner_car_ids=(adv.tie_between or [])[:need])
    raise RuntimeError("300 轮未结束")


def run(seed: int = 20260626) -> list:
    """跑一遍全链路,返回问题列表(空 = 全部正常)。打印过程到 stdout。"""
    rng = random.Random(seed)
    problems, notes = [], []
    log = print

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    db.set_engine(eng)
    try:
        # 1. 赛季 + 10 车队 + 60 车 ------------------------------------------------
        with Session(eng) as s:
            season1_id = ssvc.start_season(s, name="模拟S1").id
            fb = ["法拉利", "红牛", "梅赛德斯", "迈凯伦", "阿斯顿"]
            team_ids = []
            for i in range(10):
                if i < 5:
                    t = tsvc.create_team(s, type=TeamType.FACTORY, brand=fb[i], name=None)
                else:
                    t = tsvc.create_team(s, type=TeamType.INDEPENDENT, brand=None, name=f"独立队{i}")
                team_ids.append(t.id)
            indie = ["威廉姆斯", "哈斯", "无", "小红牛", "无"]
            ncars = 0
            for ti, tid in enumerate(team_ids):
                t = s.get(Team, tid)
                for cat in CATS:
                    for k in range(2):
                        brand = t.brand if t.type == TeamType.FACTORY else rng.choice(indie)
                        status = rng.choice([CarStatus.LONG, CarStatus.SHORT])
                        csvc.create_car(s, nickname=f"T{ti}-{cat.value}-{k}", category=cat,
                                        brand=brand, casting="X", description="",
                                        team_id=tid, signed_status=status)
                        ncars += 1
            long_n = len(s.exec(select(Car).where(Car.status == CarStatus.LONG)).all())
            short_n = len(s.exec(select(Car).where(Car.status == CarStatus.SHORT)).all())
            log(f"[建库] 车队={len(team_ids)} 赛车={ncars} 长期={long_n} 短期={short_n}")
            if ncars != 60:
                problems.append(f"赛车数应 60,实 {ncars}")

        # 2. 每级别 2 单人 + 2 车队 -----------------------------------------------
        log("\n[比赛]")
        with Session(eng) as s:
            for cat in CATS:
                active = [c.id for c in s.exec(select(Car).where(
                    Car.category == cat, Car.status.in_(ACTIVE_STATUSES))).all()]
                for _ in range(2):
                    try:
                        r = T.create_race(s, category=cat, pro_level=ProLevel.PRO,
                                          format=RaceFormat.SOLO, car_ids=active,
                                          seed=rng.randint(0, 10 ** 6))
                        res = _play_race(s, r.id, rng)
                        log(f"  {cat.value} 单人 OK 冠军={res.ranking[0]}")
                    except Exception as e:
                        problems.append(f"{cat.value} 单人赛异常: {e!r}")
                        log(f"  {cat.value} 单人 ERR {e!r}")
                for _ in range(2):
                    try:
                        r = T.create_team_race(s, category=cat, pro_level=ProLevel.PRO,
                                               team_ids=list(team_ids), seed=rng.randint(0, 10 ** 6))
                        res = _play_race(s, r.id, rng)
                        log(f"  {cat.value} 车队 OK 前三={res.ranking[:3]}")
                    except Exception as e:
                        problems.append(f"{cat.value} 车队赛异常: {e!r}")
                        log(f"  {cat.value} 车队 ERR {e!r}")

        # 3. MMR / 积分 / 薪资 / 预算 ----------------------------------------------
        with Session(eng) as s:
            log("\n[MMR 零和]")
            for cat in CATS:
                cars = s.exec(select(Car).where(Car.category == cat)).all()
                sm = [c.season_mmr for c in cars]
                moved = sum(1 for x in sm if abs(x - 1500) > 0.5)
                drift = sum(sm) - 1500 * len(cars)
                log(f"  {cat.value}: {min(sm):.0f}~{max(sm):.0f} 变动{moved}/{len(cars)} 漂移{drift:+.3f}")
                if moved == 0:
                    problems.append(f"{cat.value} MMR 未变")
                if abs(drift) > 1.0:
                    problems.append(f"{cat.value} MMR 零和漂移 {drift:.2f}")
            tot = sum(st.team_season_points(s, tid, season1_id) for tid in team_ids)
            log(f"[车队积分] 总计 {tot}")
            if tot == 0:
                problems.append("车队积分全 0")
            allv = [sal.compute_salary(s, c, season1_id) for c in s.exec(select(Car)).all()]
            log(f"[薪资] {min(allv)}~{max(allv)} 均{sum(allv) / len(allv):.0f}")
            if min(allv) < 30:
                problems.append(f"薪资低于下限 30:{min(allv)}")

        # 4. 赛季结束 快照/重置 ---------------------------------------------------
        with Session(eng) as s:
            pre_hist = {c.id: c.historical_mmr for c in s.exec(select(Car)).all()}
            ssvc.end_season(s, season1_id)
            snaps = s.exec(select(CarSeasonMMR).where(CarSeasonMMR.season_id == season1_id)).all()
            cars = s.exec(select(Car)).all()
            reset_ok = all(abs(c.season_mmr - 1500) < 1e-6 for c in cars)
            hist_ok = all(abs(c.historical_mmr - pre_hist[c.id]) < 1e-6 for c in cars)
            log(f"\n[赛季结束] 快照{len(snaps)} 赛季MMR重置={reset_ok} 历史不变={hist_ok}")
            if len(snaps) != 60:
                problems.append(f"快照{len(snaps)}!=60")
            if not reset_ok:
                problems.append("赛季 MMR 未重置")
            if not hist_ok:
                problems.append("历史 MMR 被改")

        # 5. 转会选秀(逐队逐类别 + 挖角 + 重置)----------------------------------
        with Session(eng) as s:
            ssvc.start_season(s, name="模拟S2")
            ref = market.reference_season(s)
            log(f"\n[转会选秀] 参照赛季={ref.name}")
            if ref.id != season1_id:
                problems.append(f"参照赛季应为 S1,实为 {ref.name}")

            pre = {c.id: (c.team_id, c.status) for c in s.exec(select(Car)).all()}
            draft = md.open_draft(s)
            snaps = s.exec(select(DraftCarSnapshot).where(
                DraftCarSnapshot.draft_id == draft.id)).all()
            unchanged = all((s.get(Car, cid).team_id, s.get(Car, cid).status) == pre[cid]
                            for cid in pre)
            log(f"  开盘:草稿快照 {len(snaps)};开盘不改动任何车={unchanged}")
            if len(snaps) != len(pre):
                problems.append(f"草稿快照{len(snaps)}!={len(pre)}")
            if not unchanged:
                problems.append("开盘改动了车辆归属")

            guard = 0
            while True:
                guard += 1
                if guard > 100:
                    problems.append("选秀队列未收敛(>100)")
                    break
                top = md._highest_unlocked(s, md.get_draft(s))
                if top is None:
                    break
                md.enter_team(s, top)
                for cat in sorted(CATS, key=lambda c: not md._has_long(s, top, c)):
                    rec = md.category_recommendation(s, top, cat)
                    slots = (rec["strengthen"] + [None, None])[:2]
                    try:
                        md.lock_category(s, top, cat, slots)
                    except md.DraftError as e:
                        problems.append(f"{s.get(Team, top).name}/{cat.value} 建议锁定被拒: {e}")
                md.confirm_team(s, top)

            d = md.get_draft(s)
            all_locked = md.locked_team_ids(d) == set(team_ids)
            log(f"  全部车队已确认={all_locked}({len(md.locked_team_ids(d))}/{len(team_ids)})")
            if not all_locked:
                problems.append("有车队未被确认")

            # 现役数越界(>2/负数);n==1 的合法性已由 lock_category 在锁定时把关
            for tid in team_ids:
                for cat in CATS:
                    n = tsvc.active_count(s, tid, cat, None)
                    if n not in (0, 1, 2):
                        problems.append(f"{s.get(Team, tid).name}/{cat.value} 现役数越界 n={n}")
            rejected = any("锁定被拒" in p for p in problems)
            log(f"  锁定阶段无一被拒={'是' if not rejected else '否'}")

            # 预算不超支(唯一例外=仅长期车且长期本身超预算)
            for tid in team_ids:
                committed = market.committed_salary(s, tid, ref.id)
                budget = bud.compute_budget(s, s.get(Team, tid), ref.id)
                if committed > budget:
                    actives = s.exec(select(Car).where(
                        Car.team_id == tid, Car.status.in_(ACTIVE_STATUSES))).all()
                    if not all(c.status == CarStatus.LONG for c in actives):
                        problems.append(f"{s.get(Team, tid).name} 超预算非法:{committed}>{budget}")

            poached = [cid for cid in pre if s.get(Car, cid).team_id not in (None, pre[cid][0])]
            log(f"  挖角/换队={len(poached)} 辆")

            md.reset_draft(s)
            restored = all((s.get(Car, cid).team_id, s.get(Car, cid).status) == pre[cid]
                           for cid in pre)
            log(f"  一键重置还原所有车={restored}")
            if not restored:
                problems.append("重置未能还原到开盘前状态")
    finally:
        db.set_engine(None)

    log("\n" + "=" * 48)
    if problems:
        log(f"发现 {len(problems)} 个问题:")
        for p in problems:
            log("  X", p)
    else:
        log("全链路自检通过,无问题。")
    return problems


def main() -> int:
    problems = run()
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
