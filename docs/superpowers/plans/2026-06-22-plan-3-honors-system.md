# 计划三:荣誉系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **前置:** 计划一、二已完成。

**Goal:** 实现荣誉系统:赛车 MMR(按等级、赛季+历史双天梯、Elo 算法,每个专业小组结算一次)、车队积分(赛季制、专业单人前3 +5/4/3、专业车队前3 +10/8/6、记录来源)、赛季结束(MMR 快照 + 赛季 MMR 重置)、各类榜单页面,并把计划一/二里预留的占位(个人页荣誉、车队积分来源、赛季页)补成真实数据。

**Architecture:** Elo 与车队积分计算是纯函数(`mmr.py`、`standings.py`);结算钩子挂在计划二的 `tournament.advance_round` 上——每轮推进时为本轮每个**专业**小组结算一次 MMR(幂等),比赛结束时按最终名次发放车队积分。赛季结束逻辑挂在计划一 `seasons.end_season` 的预留钩子上。

**Tech Stack:** 同前。

---

## 文件结构(本计划新增/涉及)

```
app/
  models.py                 # 追加 TeamPointEntry;Group 追加 mmr_settled 字段
  config.py                 # 追加 ELO_K
  services/
    mmr.py                  # Elo 纯函数 + 应用到双天梯
    standings.py            # 车队积分发放/查询 纯函数+持久化
    tournament.py           # advance_round 内挂 MMR + 车队积分钩子
    seasons.py              # end_season 内挂 MMR 快照 + 重置
  routers/
    standings.py            # 荣誉榜页面(MMR 榜 + 车队积分榜)
  templates/
    standings.html
    season_detail.html      # 完善:赛季成绩 + 末位 MMR + 车队积分榜
tests/
  test_mmr.py
  test_standings.py
  test_honors_integration.py
  test_season_end.py
```

---

## Task 1: 模型与配置补充

**Files:**
- Modify: `app/config.py`
- Modify: `app/models.py`
- Test: `tests/test_standings.py`(建表冒烟)

- [ ] **Step 1: config 追加 Elo K 与车队积分表**

```python
# app/config.py 追加
ELO_K = 24.0
SOLO_TEAM_POINTS = {1: 5, 2: 4, 3: 3}   # 专业单人锦标赛前3名→车队
TEAM_TEAM_POINTS = {1: 10, 2: 8, 3: 6}  # 专业车队锦标赛前3名→车队
```

- [ ] **Step 2: models 追加 TeamPointEntry,Group 加 mmr_settled**

```python
# app/models.py:在 Group 类里追加字段
    mmr_settled: bool = False
```

```python
# app/models.py 末尾追加
class TeamPointEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    season_id: int = Field(foreign_key="season.id")
    team_id: int = Field(foreign_key="team.id")
    points: int
    source_car_id: Optional[int] = Field(default=None, foreign_key="car.id")
    race_id: Optional[int] = Field(default=None, foreign_key="race.id")
    description: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] **Step 3: 写建表冒烟测试**

```python
# tests/test_standings.py
from app.models import TeamPointEntry


def test_team_point_entry_table(session):
    from app.services import seasons as ssvc
    s = ssvc.start_season(session, name="2026 S1")
    e = TeamPointEntry(season_id=s.id, team_id=1, points=5, description="测试")
    session.add(e); session.commit(); session.refresh(e)
    assert e.id is not None and e.points == 5
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_standings.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/config.py app/models.py tests/test_standings.py
git commit -m "feat: honors models and config"
```

---

## Task 2: MMR(Elo)纯函数

**Files:**
- Create: `app/services/mmr.py`
- Test: `tests/test_mmr.py`

规则:小组 4 场后按总分排名;两两对战,排前=输、排后=赢、同分=平;`E=1/(1+10^((对手-自己)/400))`,`S∈{1,0,0.5}`,`ΔMMR=K×(S−E)`,组内所有对手求和。零和。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_mmr.py
import pytest
from app.services import mmr


def test_equal_ratings_winner_gains_loser_loses_symmetric():
    # 两车同分 1500,car 10 赢 car 20
    ratings = {10: 1500.0, 20: 1500.0}
    totals = {10: 10, 20: 6}
    d = mmr.elo_deltas(ratings, totals, k=24)
    assert round(d[10], 2) == 12.0
    assert round(d[20], 2) == -12.0


def test_zero_sum_in_group_of_four():
    ratings = {10: 1500.0, 20: 1500.0, 30: 1500.0, 40: 1500.0}
    totals = {10: 18, 20: 14, 30: 8, 40: 6}
    d = mmr.elo_deltas(ratings, totals, k=24)
    assert round(sum(d.values()), 6) == 0.0
    assert d[10] > 0 and d[40] < 0


def test_upset_gives_more_points():
    # 1400 赢 1600
    ratings = {10: 1400.0, 20: 1600.0}
    totals = {10: 10, 20: 6}
    d = mmr.elo_deltas(ratings, totals, k=24)
    assert d[10] > 12          # 爆冷涨更多
    assert round(d[10], 2) == 17.0
    assert round(d[20], 2) == -17.0


def test_tie_counts_as_half():
    ratings = {10: 1500.0, 20: 1500.0}
    totals = {10: 8, 20: 8}    # 同分=平
    d = mmr.elo_deltas(ratings, totals, k=24)
    assert round(d[10], 2) == 0.0 and round(d[20], 2) == 0.0
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_mmr.py -v`
Expected: FAIL,`ModuleNotFoundError`

- [ ] **Step 3: 写 mmr.py**

```python
# app/services/mmr.py
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
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_mmr.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/mmr.py tests/test_mmr.py
git commit -m "feat: Elo MMR pure functions"
```

---

## Task 3: 把 MMR 应用到双天梯(持久化)

**Files:**
- Modify: `app/services/mmr.py`(新增 `settle_group_mmr`)
- Test: `tests/test_mmr.py`(追加)

每个**专业**小组录完后结算一次:用各车当前 `season_mmr` 算赛季天梯增量、当前 `historical_mmr` 算历史天梯增量,**分别**更新。用 `Group.mmr_settled` 保证幂等。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_mmr.py 追加
from sqlmodel import select
from app.models import Car, Group, Heat
from app.enums import Category, ProLevel, RaceFormat
from app.services import seasons as ssvc, cars as csvc, tournament as T


def _solo_group_recorded(session, totals_order):
    """建一个 4 车专业单人赛,录入使名次=totals_order 顺序,返回 group。"""
    ssvc.start_season(session, name="2026 S1")
    from app.services import teams as tsvc
    t = tsvc.create_team(session, type=tsvc.TeamType.INDEPENDENT, brand=None, name="独立队") \
        if False else None
    ids = []
    for i in range(4):
        c = csvc.create_car(session, nickname=f"车{i}", category=Category.GT3,
                            brand="法拉利", casting="", description="", team_id=None)
        ids.append(c.id)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=ids, seed=1)
    grp = session.exec(select(Group)).first()
    members = [m.car_id for m in session.exec(
        select(__import__('app.models', fromlist=['GroupMember']).GroupMember)
        .where(__import__('app.models', fromlist=['GroupMember']).GroupMember.group_id == grp.id)).all()]
    for h in session.exec(select(Heat).where(Heat.group_id == grp.id)).all():
        T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(members)})
    return grp, members


def test_settle_group_mmr_updates_both_ladders(session):
    grp, members = _solo_group_recorded(session, None)
    from app.services import mmr
    mmr.settle_group_mmr(session, grp.id)
    winner = session.get(Car, members[0])
    loser = session.get(Car, members[-1])
    assert winner.season_mmr > 1500 and winner.historical_mmr > 1500
    assert loser.season_mmr < 1500 and loser.historical_mmr < 1500
    session.refresh(grp); assert grp.mmr_settled is True


def test_settle_group_mmr_idempotent(session):
    grp, members = _solo_group_recorded(session, None)
    from app.services import mmr
    mmr.settle_group_mmr(session, grp.id)
    first = session.get(Car, members[0]).season_mmr
    mmr.settle_group_mmr(session, grp.id)   # 再次调用不应重复加分
    assert session.get(Car, members[0]).season_mmr == first
```

> 简化:上面 fixture 写法略繁;实现者可改为直接用 `from app.models import GroupMember` 顶部导入后简化。关键断言不变。

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_mmr.py -k settle -v`
Expected: FAIL,`AttributeError: ... 'settle_group_mmr'`

- [ ] **Step 3: 在 mmr.py 追加 settle_group_mmr**

```python
# app/services/mmr.py 追加
from sqlmodel import Session, select
from app.models import Car, Group, Heat, HeatResult
from app.services import scoring


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
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_mmr.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/mmr.py tests/test_mmr.py
git commit -m "feat: apply MMR to season and historical ladders"
```

---

## Task 4: 车队积分发放(纯逻辑 + 持久化)

**Files:**
- Create: `app/services/standings.py`
- Test: `tests/test_standings.py`(追加)

专业单人锦标赛:最终名次前 3 的**车**给其车队 +5/4/3(无车队跳过)。专业车队锦标赛:前 3 的**车队** +10/8/6。每笔记 `TeamPointEntry`(含来源)。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_standings.py 追加
from app.enums import Category, TeamType
from app.services import seasons as ssvc, cars as csvc, teams as tsvc, standings as st
from sqlmodel import select


def test_award_solo_points_to_car_teams(session):
    s = ssvc.start_season(session, name="2026 S1")
    t1 = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    t2 = tsvc.create_team(session, type=TeamType.FACTORY, brand="保时捷", name=None)
    c1 = csvc.create_car(session, nickname="法1", category=Category.GT3,
                         brand="法拉利", casting="", description="", team_id=t1.id)
    c2 = csvc.create_car(session, nickname="保1", category=Category.GT3,
                         brand="保时捷", casting="", description="", team_id=t2.id)
    c3 = csvc.create_car(session, nickname="无队", category=Category.GT3,
                         brand="奥迪", casting="", description="", team_id=None)
    st.award_solo(session, season_id=s.id, race_id=1, ranking=[c1.id, c2.id, c3.id])
    assert st.team_season_points(session, t1.id, s.id) == 5
    assert st.team_season_points(session, t2.id, s.id) == 4
    # 第三名无车队 → 无记录
    entries = session.exec(select(st.TeamPointEntry)).all()
    assert len(entries) == 2


def test_award_team_points(session):
    s = ssvc.start_season(session, name="2026 S1")
    t1 = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    t2 = tsvc.create_team(session, type=TeamType.FACTORY, brand="保时捷", name=None)
    st.award_team(session, season_id=s.id, race_id=1, ranking=[t1.id, t2.id])
    assert st.team_season_points(session, t1.id, s.id) == 10
    assert st.team_season_points(session, t2.id, s.id) == 8


def test_points_are_season_scoped(session):
    s1 = ssvc.start_season(session, name="2026 S1")
    t1 = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    st.award_team(session, season_id=s1.id, race_id=1, ranking=[t1.id])
    ssvc.end_season(session, s1.id)
    s2 = ssvc.start_season(session, name="2026 S2")
    assert st.team_season_points(session, t1.id, s2.id) == 0   # 新赛季清零
    assert st.team_season_points(session, t1.id, s1.id) == 10  # 旧赛季仍在


def test_standings_board_sorted(session):
    s = ssvc.start_season(session, name="2026 S1")
    t1 = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    t2 = tsvc.create_team(session, type=TeamType.FACTORY, brand="保时捷", name=None)
    st.award_team(session, season_id=s.id, race_id=1, ranking=[t2.id, t1.id])
    board = st.team_board(session, s.id)
    assert board[0][0].id == t2.id and board[0][1] == 10
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_standings.py -v`
Expected: FAIL

- [ ] **Step 3: 写 standings.py**

```python
# app/services/standings.py
from sqlmodel import Session, select
from app.models import TeamPointEntry, Team, Car
from app.config import SOLO_TEAM_POINTS, TEAM_TEAM_POINTS


def _add_entry(session: Session, *, season_id: int, team_id: int, points: int,
               source_car_id, race_id, description: str) -> None:
    session.add(TeamPointEntry(season_id=season_id, team_id=team_id, points=points,
                               source_car_id=source_car_id, race_id=race_id,
                               description=description))


def award_solo(session: Session, *, season_id: int, race_id: int,
               ranking: list[int]) -> None:
    """ranking: 车 id 的最终名次列表。前 3 名的车给其车队加分。"""
    for pos, car_id in enumerate(ranking[:3], start=1):
        car = session.get(Car, car_id)
        if car is None or car.team_id is None:
            continue
        pts = SOLO_TEAM_POINTS[pos]
        _add_entry(session, season_id=season_id, team_id=car.team_id, points=pts,
                   source_car_id=car_id, race_id=race_id,
                   description=f"{car.nickname} · 单人锦标赛第 {pos} 名")
    session.commit()


def award_team(session: Session, *, season_id: int, race_id: int,
               ranking: list[int]) -> None:
    """ranking: 车队 id 的最终名次列表。前 3 名车队加分。"""
    for pos, team_id in enumerate(ranking[:3], start=1):
        team = session.get(Team, team_id)
        if team is None:
            continue
        pts = TEAM_TEAM_POINTS[pos]
        _add_entry(session, season_id=season_id, team_id=team_id, points=pts,
                   source_car_id=None, race_id=race_id,
                   description=f"车队 · 车队锦标赛第 {pos} 名")
    session.commit()


def team_season_points(session: Session, team_id: int, season_id: int) -> int:
    rows = session.exec(select(TeamPointEntry).where(
        TeamPointEntry.team_id == team_id,
        TeamPointEntry.season_id == season_id)).all()
    return sum(r.points for r in rows)


def team_point_sources(session: Session, team_id: int,
                       season_id: int) -> list[TeamPointEntry]:
    return list(session.exec(select(TeamPointEntry).where(
        TeamPointEntry.team_id == team_id,
        TeamPointEntry.season_id == season_id)
        .order_by(TeamPointEntry.id)).all())


def team_board(session: Session, season_id: int) -> list[tuple[Team, int]]:
    teams = session.exec(select(Team)).all()
    board = [(t, team_season_points(session, t.id, season_id)) for t in teams]
    board.sort(key=lambda x: x[1], reverse=True)
    return board
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_standings.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/standings.py tests/test_standings.py
git commit -m "feat: team points awarding and boards"
```

---

## Task 5: 把 MMR 与车队积分钩进赛事推进

**Files:**
- Modify: `app/services/tournament.py`
- Test: `tests/test_honors_integration.py`

在 `advance_round` 中:
1. 通过「所有小组录完」检查后,对本轮**专业**小组各调用一次 `settle_group_mmr`(幂等)。
2. 决赛结束时,按最终名次发放车队积分(单人 `award_solo`;车队 `award_team`)。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_honors_integration.py
from sqlmodel import select
from app.enums import Category, ProLevel, RaceFormat, TeamType
from app.services import (seasons as ssvc, cars as csvc, teams as tsvc,
                          tournament as T, standings as st)
from app.models import Car, Race, RaceRound, Group, GroupMember, Heat


def _record_all(session, race_id):
    rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race_id)
                       .order_by(RaceRound.number.desc())).first()
    for g in session.exec(select(Group).where(Group.round_id == rnd.id)).all():
        members = [m.car_id for m in session.exec(select(GroupMember)
                   .where(GroupMember.group_id == g.id)).all()]
        for h in session.exec(select(Heat).where(Heat.group_id == g.id)).all():
            T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(members)})


def _pro_solo_4(session):
    s = ssvc.start_season(session, name="2026 S1")
    teams = [tsvc.create_team(session, type=TeamType.FACTORY, brand=b, name=None)
             for b in ["法拉利", "保时捷", "奥迪", "宝马"]]
    ids = []
    for i, t in enumerate(teams):
        c = csvc.create_car(session, nickname=f"车{i}", category=Category.GT3,
                            brand=t.brand, casting="", description="", team_id=t.id)
        ids.append(c.id)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=ids, seed=1)
    return s, race, ids, teams


def test_finish_pro_solo_updates_mmr_and_team_points(session):
    s, race, ids, teams = _pro_solo_4(session)
    _record_all(session, race.id)
    result = T.advance_round(session, race.id)
    assert result.kind == "finished"
    # MMR 改变
    assert session.get(Car, result.ranking[0]).season_mmr > 1500
    # 车队积分:冠军车的车队 +5
    champ = session.get(Car, result.ranking[0])
    assert st.team_season_points(session, champ.team_id, s.id) == 5


def test_exhibition_race_does_not_change_mmr_or_points(session):
    s = ssvc.start_season(session, name="2026 S1")
    ids = [csvc.create_car(session, nickname=f"车{i}", category=Category.GT3,
            brand="法拉利", casting="", description="", team_id=None).id
           for i in range(4)]
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.EXHIBITION,
                         format=RaceFormat.SOLO, car_ids=ids, seed=1)
    _record_all(session, race.id)
    T.advance_round(session, race.id)
    assert session.get(Car, ids[0]).season_mmr == 1500
    from app.models import TeamPointEntry
    assert session.exec(select(TeamPointEntry)).all() == []
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_honors_integration.py -v`
Expected: FAIL(MMR/积分未变)

- [ ] **Step 3: 修改 tournament.advance_round 挂钩**

在 `advance_round` 里,「needs_results」检查通过之后、其余逻辑之前,加入 MMR 结算;在「决赛 finished」分支里发放车队积分。

```python
# app/services/tournament.py — 修改 advance_round
from app.enums import ProLevel
from app.services import mmr as mmr_svc, standings as st_svc


def advance_round(session: Session, race_id: int,
                  seed: Optional[int] = None) -> AdvanceResult:
    race = session.get(Race, race_id)
    rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race_id)
                       .order_by(RaceRound.number.desc())).first()
    groups = _round_groups(session, rnd.id)

    not_done = [g.id for g in groups if not group_recorded(session, g.id)]
    if not_done:
        return AdvanceResult(kind="needs_results", pending_group_ids=not_done)

    # 专业赛:本轮每组结算一次 MMR(幂等)
    if race.pro_level == ProLevel.PRO:
        for g in groups:
            mmr_svc.settle_group_mmr(session, g.id)

    if rnd.is_final:
        totals = scoring.group_totals(_group_results(session, groups[0].id))
        ranking = scoring.final_ranking(totals)
        race.status = RaceStatus.FINISHED
        session.add(race); session.commit()
        if race.pro_level == ProLevel.PRO:
            if race.format == RaceFormat.SOLO:
                st_svc.award_solo(session, season_id=race.season_id,
                                  race_id=race.id, ranking=ranking)
            else:
                team_ranking = _team_final_ranking(session, race, groups[0])
                st_svc.award_team(session, season_id=race.season_id,
                                  race_id=race.id, ranking=team_ranking)
        return AdvanceResult(kind="finished", ranking=ranking)

    advancers: list[int] = []
    for g in groups:
        adv = settle_group(session, g.id)
        if adv.advancers is None:
            return AdvanceResult(kind="needs_decision", pending_group_ids=[g.id])
        advancers.extend(adv.advancers)

    _build_round(session, race, number=rnd.number + 1, car_ids=advancers, seed=seed)
    return AdvanceResult(kind="next_round")


def _team_final_ranking(session: Session, race: Race, final_group: Group) -> list[int]:
    """车队赛决赛组(2 队)→ [胜队, 负队]。第 3 名留待细化(见 spec §8)。"""
    res = settle_team_group(session, final_group.id)
    a, b = final_group.team_a_id, final_group.team_b_id
    if res.winner_team_id == b:
        return [b, a]
    return [a, b]
```

> 说明:`_team_final_ranking` 目前只产出前 2 名 → `award_team` 发 10/8。第 3 名(半决赛淘汰队)的发放规则在 spec §8「待打磨」,本计划不实现,避免歧义。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_honors_integration.py -v`
Expected: PASS

- [ ] **Step 5: 全量回归(确保未破坏计划二)+ 提交**

Run: `pytest -v`
Expected: 全部 PASS

```bash
git add app/services/tournament.py tests/test_honors_integration.py
git commit -m "feat: hook MMR and team points into race progression"
```

---

## Task 6: 赛季结束——MMR 快照 + 赛季 MMR 重置

**Files:**
- Modify: `app/services/seasons.py`
- Test: `tests/test_season_end.py`

赛季结束时:为每辆车把当前 `season_mmr` 存入 `CarSeasonMMR` 快照;然后把所有车的 `season_mmr` 重置为 `INITIAL_MMR`;`historical_mmr` 不动。车队积分天然按赛季隔离(新赛季无 entry),无需清零动作。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_season_end.py
from sqlmodel import select
from app.models import Car, CarSeasonMMR
from app.enums import Category
from app.services import seasons as ssvc, cars as csvc
from app.config import INITIAL_MMR


def test_end_season_snapshots_and_resets_mmr(session):
    s = ssvc.start_season(session, name="2026 S1")
    c = csvc.create_car(session, nickname="车", category=Category.GT3,
                        brand="法拉利", casting="", description="", team_id=None)
    c.season_mmr = 1640.0
    c.historical_mmr = 1655.0
    session.add(c); session.commit()
    ssvc.end_season(session, s.id)
    snap = session.exec(select(CarSeasonMMR).where(
        CarSeasonMMR.season_id == s.id, CarSeasonMMR.car_id == c.id)).one()
    assert snap.mmr == 1640.0
    session.refresh(c)
    assert c.season_mmr == INITIAL_MMR        # 赛季 MMR 重置
    assert c.historical_mmr == 1655.0          # 历史 MMR 不变
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_season_end.py -v`
Expected: FAIL(快照不存在 / season_mmr 未重置)

- [ ] **Step 3: 修改 seasons.end_season**

把计划一里 `end_season` 中预留钩子位置替换为真实实现:

```python
# app/services/seasons.py — end_season 内,设置 FINISHED 之前插入:
    from app.models import Car, CarSeasonMMR
    from app.config import INITIAL_MMR
    cars = session.exec(select(Car)).all()
    for c in cars:
        session.add(CarSeasonMMR(season_id=s.id, car_id=c.id, mmr=c.season_mmr))
        c.season_mmr = INITIAL_MMR
        session.add(c)
    session.commit()
```

(确保 `from sqlmodel import select` 已在 seasons.py 顶部导入。)

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_season_end.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/seasons.py tests/test_season_end.py
git commit -m "feat: season end MMR snapshot and reset"
```

---

## Task 7: 荣誉榜页面(MMR 榜 + 车队积分总榜)

**Files:**
- Create: `app/routers/standings.py`
- Create: `app/templates/standings.html`
- Modify: `app/main.py`(注册 router)
- Test: `tests/test_standings.py`(追加路由测试)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_standings.py 追加
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_standings_page_shows_mmr_and_team_board(engine, session):
    s = ssvc.start_season(session, name="2026 S1")
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    c = csvc.create_car(session, nickname="法1", category=Category.GT3,
                        brand="法拉利", casting="", description="", team_id=t.id)
    st.award_team(session, season_id=s.id, race_id=1, ranking=[t.id])
    r = client.get("/standings")
    assert r.status_code == 200
    assert "法1" in r.text and "法拉利车队" in r.text


def test_standings_mmr_filtered_by_category(engine, session):
    ssvc.start_season(session, name="2026 S1")
    csvc.create_car(session, nickname="GT3车", category=Category.GT3,
                    brand="法拉利", casting="", description="", team_id=None)
    csvc.create_car(session, nickname="F1车", category=Category.F1,
                    brand="法拉利", casting="", description="", team_id=None)
    r = client.get("/standings?category=GT3")
    assert "GT3车" in r.text and "F1车" not in r.text
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_standings.py -k page -v`
Expected: FAIL(404)

- [ ] **Step 3: 写 standings.py 路由**

```python
# app/routers/standings.py
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select
from app.db import get_session
from app.models import Car
from app.enums import Category
from app.services import seasons as ssvc, standings as st
from app.routers.pages import templates

router = APIRouter()


@router.get("/standings", response_class=HTMLResponse)
def standings_page(request: Request, category: str = "GT3",
                   season_mode: str = "season",
                   session: Session = Depends(get_session)):
    cat = Category(category)
    use_hist = season_mode == "history"
    cars = session.exec(select(Car).where(Car.category == cat)).all()
    cars.sort(key=lambda c: c.historical_mmr if use_hist else c.season_mmr,
              reverse=True)
    active = ssvc.get_active_season(session)
    board = st.team_board(session, active.id) if active else []
    return templates.TemplateResponse("standings.html", {
        "request": request, "cars": cars, "category": category,
        "season_mode": season_mode, "board": board,
        "use_hist": use_hist})
```

- [ ] **Step 4: 写 standings.html**

```html
<!-- app/templates/standings.html -->
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h2>赛车 MMR 榜</h2>
  <form method="get" action="/standings" style="display:flex;gap:8px">
    <select name="category" onchange="this.form.submit()">
      {% for c in ["F1","GT3","公路车"] %}
      <option value="{{ c }}" {{ "selected" if category==c else "" }}>{{ c }}</option>
      {% endfor %}
    </select>
    <select name="season_mode" onchange="this.form.submit()">
      <option value="season" {{ "selected" if not use_hist else "" }}>赛季榜</option>
      <option value="history" {{ "selected" if use_hist else "" }}>历史榜</option>
    </select>
  </form>
  <ol>
    {% for c in cars %}
    <li><a href="/cars/{{ c.id }}">{{ c.nickname }}</a> —
      {{ (c.historical_mmr if use_hist else c.season_mmr) | round | int }}</li>
    {% else %}<li>暂无赛车</li>{% endfor %}
  </ol>
</div>
<div class="card">
  <h2>车队积分总榜(本赛季)</h2>
  <ol>
    {% for team, pts in board %}
    <li><a href="/teams/{{ team.id }}">{{ team.name }}</a> — {{ pts }} 分</li>
    {% else %}<li>暂无</li>{% endfor %}
  </ol>
</div>
{% endblock %}
```

- [ ] **Step 5: main.py 注册路由**

```python
from app.routers import standings  # noqa: E402
app.include_router(standings.router)
```

- [ ] **Step 6: 运行确认通过**

Run: `pytest tests/test_standings.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add app/routers/standings.py app/templates/standings.html app/main.py tests/test_standings.py
git commit -m "feat: standings page (MMR ladders + team board)"
```

---

## Task 8: 补全个人页 / 车队页 / 赛季页的真实荣誉数据

**Files:**
- Modify: `app/routers/cars.py`(car_detail 的 honors)
- Modify: `app/routers/teams.py`(team_detail 的积分与来源)
- Modify: `app/routers/seasons.py` + `app/templates/season_detail.html`
- Test: `tests/test_pages.py`(追加)、`tests/test_seasons_routes.py`(追加)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pages.py 追加(顶部已 import client, csvc, tsvc, ssvc, select)
from app.enums import ProLevel, RaceFormat
from app.services import tournament as T, standings as st


def test_team_detail_shows_points_and_sources(engine, session):
    s = ssvc.start_season(session, name="2026 S1")
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    c = csvc.create_car(session, nickname="法1", category=Category.GT3,
                        brand="法拉利", casting="", description="", team_id=t.id)
    st.award_solo(session, season_id=s.id, race_id=1, ranking=[c.id])
    r = client.get(f"/teams/{t.id}")
    assert "5" in r.text and "单人锦标赛第 1 名" in r.text
```

```python
# tests/test_seasons_routes.py 追加
def test_season_detail_shows_team_board(engine, session):
    from app.services import teams as tsvc, standings as st
    from app.enums import TeamType
    s = svc.start_season(session, name="2026 S1")
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    st.award_team(session, season_id=s.id, race_id=1, ranking=[t.id])
    r = client.get(f"/seasons/{s.id}")
    assert "法拉利车队" in r.text and "10" in r.text
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_pages.py -k team_detail_shows_points tests/test_seasons_routes.py -k season_detail -v`
Expected: FAIL

- [ ] **Step 3: 更新 teams.team_detail 上下文**

把计划一 `team_detail` 路由里 `season_points=0` / `point_sources=[]` 替换为真实数据:

```python
# app/routers/teams.py — team_detail 内
from app.services import standings as st, seasons as ssvc
    active = ssvc.get_active_season(session)
    season_points = st.team_season_points(session, team_id, active.id) if active else 0
    sources = (st.team_point_sources(session, team_id, active.id) if active else [])
    point_sources = [f"+{e.points} {e.description}" for e in sources]
```

并把这两个变量传入 `TemplateResponse`(替换原 `season_points`/`point_sources`)。

- [ ] **Step 4: 更新 cars.car_detail 的 honors**

把计划一 `car_detail` 里 `honors = []` 替换为按车队积分来源 + 历史赛季 MMR 快照拼装:

```python
# app/routers/cars.py — car_detail 内
from app.models import TeamPointEntry, CarSeasonMMR
    honors = []
    for e in session.exec(select(TeamPointEntry).where(
            TeamPointEntry.source_car_id == car_id)).all():
        honors.append(f"为车队贡献 +{e.points}:{e.description}")
    for snap in session.exec(select(CarSeasonMMR).where(
            CarSeasonMMR.car_id == car_id)).all():
        honors.append(f"赛季快照 MMR:{round(snap.mmr)}")
```

- [ ] **Step 5: 完善 season_detail.html + 路由**

```python
# app/routers/seasons.py — season_detail 内,补充上下文
from app.services import standings as st
from app.models import Race
    board = st.team_board(session, season_id)
    races = session.exec(select(Race).where(Race.season_id == season_id)).all()
    # 传入 board、races
```

```html
<!-- app/templates/season_detail.html -->
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h2>{{ season.name }} <span class="tag">{{ season.status.value }}</span></h2>
  <h3>本赛季比赛</h3>
  {% for r in races %}
  <a class="row" href="/races/{{ r.id }}"><span style="flex:1">{{ r.category.value }} · {{ r.format.value }}</span><span class="tag">{{ r.status.value }}</span></a>
  {% else %}<p>暂无比赛</p>{% endfor %}
  <h3>车队积分榜</h3>
  <ol>
    {% for team, pts in board %}<li>{{ team.name }} — {{ pts }} 分</li>{% else %}<li>暂无</li>{% endfor %}
  </ol>
</div>
{% endblock %}
```

- [ ] **Step 6: 运行确认通过**

Run: `pytest tests/test_pages.py tests/test_seasons_routes.py -v`
Expected: PASS

- [ ] **Step 7: 全量回归 + 提交**

Run: `pytest -v`
Expected: 全部 PASS

```bash
git add app/routers/cars.py app/routers/teams.py app/routers/seasons.py app/templates/season_detail.html tests/test_pages.py tests/test_seasons_routes.py
git commit -m "feat: wire real honors data into car/team/season pages"
```

---

## 自检(写计划后已核对)

- **Spec 覆盖**:MMR 按等级分(榜单按 `category` 过滤,Task 7)、赛季+历史双天梯(Task 3、6、7)、初始 1500(模型默认)、仅专业赛改 MMR 且每小组结算一次(Task 5 钩子 + `ProLevel.PRO` 判断)、Elo 按分差零和(Task 2)、车队积分赛季制清零(Task 4 `test_points_are_season_scoped`)、单人前3 +5/4/3 与车队前3 +10/8/6(Task 4)、积分来源记录与展示(Task 4、8)、车队积分总榜(Task 7)、历史赛季积分榜(赛季页 Task 8)、赛季结束 MMR 快照+重置(Task 6)、个人页 MMR 与排名(计划一 + Task 7/8)。
- **占位扫描**:无 TODO。车队赛第 3 名积分发放明确标注为 spec §8「待打磨」,并在 `_team_final_ranking` 注释——属有意的范围裁剪,非遗漏。
- **类型一致**:`elo_deltas`/`settle_group_mmr`/`award_solo`/`award_team`/`team_season_points`/`team_point_sources`/`team_board` 在定义、测试、调用处签名一致;`advance_round` 的 finished 分支区分 `RaceFormat.SOLO`/`TEAM` 调用对应发放函数;`Group.mmr_settled` 在模型、`settle_group_mmr` 中一致。
- **集成验证**:Task 5 含「表演赛不改 MMR/积分」反向测试;Task 5 Step 5 与 Task 8 Step 7 均要求 `pytest -v` 全量回归,防止破坏计划一、二。
