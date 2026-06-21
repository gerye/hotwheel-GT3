# 计划二:赛事系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **前置:** 计划一已完成(模型、数据库页面、赛季)。

**Goal:** 实现完整赛事流程:开始比赛 → 勾选参赛车 → 随机分组(可视化)→ 4 道站位安排 → 逐场录入结果 → 晋级/重组 → 决赛定名次,并支持任意步骤回退。先单人锦标赛,后车队锦标赛。

**Architecture:** 分组、站位、计分、晋级都是**纯函数算法**(`app/services/grouping.py`、`lineup.py`、`scoring.py`),便于单测;`app/services/tournament.py` 负责把算法与持久化(Round/Group/Heat/HeatResult)编排起来,并提供 undo。路由只做编排与渲染。

**Tech Stack:** 同计划一。新增随机分组用 `random`(可注入 seed 便于测试)。

---

## 文件结构(本计划新增/涉及)

```
app/
  models.py                 # 追加 Race/RaceEntry/RaceRound/Group/GroupMember/Heat/HeatResult/TieBreak
  services/
    grouping.py             # 分组算法(纯函数)
    lineup.py               # 4 道站位安排(纯函数)
    scoring.py              # 名次→积分、小组总分、晋级判定(纯函数)
    tournament.py           # 编排:建赛、建轮、录入、撤销、晋级、决赛
  routers/
    races.py                # 赛事页面与录入端点
  templates/
    races.html              # 赛事列表 + 开始新比赛
    race_new.html           # 选项 + 勾选参赛车
    race_detail.html        # 分组可视化 + 当前进度
    _group_card.html        # 单组(成员/站位表/结果)
    _heat_entry.html        # 当前场录入(HTMX 局部)
tests/
  test_grouping.py
  test_lineup.py
  test_scoring.py
  test_tournament.py
  test_team_championship.py
  test_races_routes.py
```

---

## Task 1: 赛事相关数据模型

**Files:**
- Modify: `app/models.py`
- Test: `tests/test_tournament.py`(建表冒烟)

- [ ] **Step 1: 在 models.py 追加枚举导入与表**

```python
# app/models.py 追加
from app.enums import ProLevel, RaceFormat, RaceStatus


class Race(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    season_id: int = Field(foreign_key="season.id")
    category: Category
    pro_level: ProLevel
    format: RaceFormat
    status: RaceStatus = RaceStatus.IN_PROGRESS
    started_at: datetime = Field(default_factory=datetime.utcnow)


class RaceEntry(SQLModel, table=True):
    """报名:单人赛只填 car_id;车队赛 car_id + team_id 都填。"""
    id: Optional[int] = Field(default=None, primary_key=True)
    race_id: int = Field(foreign_key="race.id")
    car_id: int = Field(foreign_key="car.id")
    team_id: Optional[int] = Field(default=None, foreign_key="team.id")


class RaceRound(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    race_id: int = Field(foreign_key="race.id")
    number: int
    is_final: bool = False


class Group(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    round_id: int = Field(foreign_key="raceround.id")
    label: str                      # A/B/C...
    team_a_id: Optional[int] = Field(default=None, foreign_key="team.id")  # 车队赛
    team_b_id: Optional[int] = Field(default=None, foreign_key="team.id")


class GroupMember(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group.id")
    car_id: int = Field(foreign_key="car.id")


class Heat(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group.id")
    number: int                     # 1..4
    recorded: bool = False


class HeatResult(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    heat_id: int = Field(foreign_key="heat.id")
    car_id: int = Field(foreign_key="car.id")
    lane: int                       # 1..4
    rank: Optional[int] = None      # 1..4;录入后填
    dnf: bool = False


class TieBreak(SQLModel, table=True):
    """并列加赛/1V1 的人工裁决结果。"""
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group.id")
    winner_car_id: Optional[int] = Field(default=None, foreign_key="car.id")
    winner_team_id: Optional[int] = Field(default=None, foreign_key="team.id")
```

- [ ] **Step 2: 写建表冒烟测试**

```python
# tests/test_tournament.py
from app.models import Race, RaceRound, Group, Heat, HeatResult
from app.enums import Category, ProLevel, RaceFormat


def test_race_tables_exist(session):
    from app.services import seasons as ssvc
    s = ssvc.start_season(session, name="2026 S1")
    r = Race(season_id=s.id, category=Category.GT3,
             pro_level=ProLevel.PRO, format=RaceFormat.SOLO)
    session.add(r); session.commit(); session.refresh(r)
    assert r.id is not None and r.status.value == "进行中"
```

- [ ] **Step 3: 运行确认通过**

Run: `pytest tests/test_tournament.py -v`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add app/models.py tests/test_tournament.py
git commit -m "feat: race domain models"
```

---

## Task 2: 分组算法(纯函数)

**Files:**
- Create: `app/services/grouping.py`
- Test: `tests/test_grouping.py`

铁律:每组 3-4 辆,绝不少于 3;优先 4 辆组,用 3 辆组凑齐。组数 = `ceil(N/4)`。无合法划分(N<3 或 N==5)时抛错。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_grouping.py
import pytest
from app.services import grouping as g


def test_sizes_16():
    assert g.group_sizes(16) == [4, 4, 4, 4]


def test_sizes_14():
    assert g.group_sizes(14) == [4, 4, 3, 3]


def test_sizes_10():
    assert g.group_sizes(10) == [4, 3, 3]


def test_sizes_6():
    assert g.group_sizes(6) == [3, 3]


def test_sizes_7():
    assert g.group_sizes(7) == [4, 3]


def test_sizes_3_and_4():
    assert g.group_sizes(3) == [3]
    assert g.group_sizes(4) == [4]


def test_invalid_counts():
    for n in (0, 1, 2, 5):
        with pytest.raises(g.GroupingError):
            g.group_sizes(n)


def test_partition_assigns_all_and_labels(deterministic):
    cars = list(range(1, 11))  # 10 辆
    groups = g.partition(cars, seed=42)
    assert [len(m) for m in [grp.members for grp in groups]] == [4, 3, 3]
    assert {c for grp in groups for c in grp.members} == set(cars)
    assert [grp.label for grp in groups] == ["A", "B", "C"]


def test_partition_is_random_with_seed():
    cars = list(range(1, 7))
    a = g.partition(cars, seed=1)
    b = g.partition(cars, seed=1)
    assert [grp.members for grp in a] == [grp.members for grp in b]
```

新增一个 fixture(在 `tests/conftest.py` 追加):

```python
@pytest.fixture()
def deterministic():
    import random
    random.seed(0)
    yield
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_grouping.py -v`
Expected: FAIL,`ModuleNotFoundError`

- [ ] **Step 3: 写 grouping.py**

```python
# app/services/grouping.py
import math
import random
from dataclasses import dataclass, field


class GroupingError(Exception):
    pass


@dataclass
class PlannedGroup:
    label: str
    members: list[int] = field(default_factory=list)


def group_sizes(n: int) -> list[int]:
    """把 n 拆成若干 3-4 的组,优先 4 辆组。"""
    if n < 3 or n == 5:
        raise GroupingError(f"{n} 辆车无法满足「每组 3-4 辆」,请调整参赛数量")
    groups = math.ceil(n / 4)
    if 3 * groups > n:                 # 理论上仅 n==5 触发,已被上面拦截
        raise GroupingError(f"{n} 辆车无法分组")
    fours = n - 3 * groups            # 4 辆组数量
    threes = groups - fours           # 3 辆组数量
    return [4] * fours + [3] * threes


def _labels(k: int) -> list[str]:
    return [chr(ord("A") + i) for i in range(k)]


def partition(car_ids: list[int], seed: int | None = None) -> list[PlannedGroup]:
    sizes = group_sizes(len(car_ids))
    pool = list(car_ids)
    rng = random.Random(seed)
    rng.shuffle(pool)
    result: list[PlannedGroup] = []
    idx = 0
    for label, size in zip(_labels(len(sizes)), sizes):
        result.append(PlannedGroup(label=label, members=pool[idx:idx + size]))
        idx += size
    return result
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_grouping.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/grouping.py tests/test_grouping.py tests/conftest.py
git commit -m "feat: grouping algorithm"
```

---

## Task 3: 站位算法(纯函数)

**Files:**
- Create: `app/services/lineup.py`
- Test: `tests/test_lineup.py`

每组 4 场,用 4 符号循环拉丁方:`heat h(0..3),lane l(0..3) → symbols[(l+h)%4]`,符号 = 车 + 不足 4 个用 `None` 补。性质:每车每场都出赛、且 4 场里 1-4 道各跑一次。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_lineup.py
from app.services import lineup as L


def test_four_cars_each_lane_once():
    cars = [10, 20, 30, 40]
    heats = L.build_lineup(cars)         # list[list[car_or_None]]，外层=场(4),内层=道(4)
    assert len(heats) == 4
    for h in heats:
        assert len(h) == 4
    # 每辆车在 4 场里把 4 个道各跑一次
    for car in cars:
        lanes = []
        for h in heats:
            lanes.append(h.index(car))
        assert sorted(lanes) == [0, 1, 2, 3]
    # 每辆车每场都出赛
    for h in heats:
        assert set(c for c in h if c is not None) == set(cars)


def test_three_cars_run_four_heats_and_have_empty_lane():
    cars = [10, 20, 30]
    heats = L.build_lineup(cars)
    assert len(heats) == 4
    for car in cars:
        # 每车每场都出赛
        assert sum(1 for h in heats if car in h) == 4
        # 4 场里访问 4 个不同道(其中含拉丁方分配)
        lanes = [h.index(car) for h in heats]
        assert sorted(lanes) == [0, 1, 2, 3]
    # 每场恰有一个空道
    for h in heats:
        assert h.count(None) == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_lineup.py -v`
Expected: FAIL,`ModuleNotFoundError`

- [ ] **Step 3: 写 lineup.py**

```python
# app/services/lineup.py
from app.config import NUM_LANES


def build_lineup(car_ids: list[int]) -> list[list[int | None]]:
    """返回 4 场 × 4 道的安排;不足 4 辆用 None 补空道。"""
    symbols: list[int | None] = list(car_ids) + [None] * (NUM_LANES - len(car_ids))
    heats: list[list[int | None]] = []
    for h in range(NUM_LANES):
        lane_to_car = [symbols[(l + h) % NUM_LANES] for l in range(NUM_LANES)]
        heats.append(lane_to_car)
    return heats
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_lineup.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/lineup.py tests/test_lineup.py
git commit -m "feat: lane lineup algorithm"
```

---

## Task 4: 计分与晋级判定(纯函数)

**Files:**
- Create: `app/services/scoring.py`
- Test: `tests/test_scoring.py`

积分:1/2/3/4 名 → 5/3/2/1;未完赛 → 0。小组总分 = 各场之和。晋级:总分前 2;若 2/3 名总分并列,需 1V1。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_scoring.py
import pytest
from app.services import scoring as sc


def test_points_for_rank():
    assert sc.points_for_rank(1) == 5
    assert sc.points_for_rank(2) == 3
    assert sc.points_for_rank(3) == 2
    assert sc.points_for_rank(4) == 1
    assert sc.points_for_rank(None) == 0   # DNF


def test_group_totals():
    # car -> list of ranks across 4 heats
    results = {10: [1, 1, 2, 1], 20: [2, 2, 1, 2], 30: [3, 3, 3, None]}
    totals = sc.group_totals(results)
    assert totals[10] == 5 + 5 + 3 + 5
    assert totals[20] == 3 + 3 + 5 + 3
    assert totals[30] == 2 + 2 + 2 + 0


def test_advancers_top_two_no_tie():
    totals = {10: 18, 20: 14, 30: 8, 40: 6}
    res = sc.resolve_advancement(totals)
    assert res.advancers == [10, 20]
    assert res.tie_between is None


def test_advancement_tie_for_second():
    totals = {10: 18, 20: 10, 30: 10, 40: 6}
    res = sc.resolve_advancement(totals)
    assert res.advancers is None          # 需 1V1
    assert set(res.tie_between) == {20, 30}
    assert res.guaranteed == [10]


def test_final_ranking_orders_by_total():
    totals = {10: 18, 20: 14, 30: 8, 40: 6}
    assert sc.final_ranking(totals) == [10, 20, 30, 40]
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_scoring.py -v`
Expected: FAIL,`ModuleNotFoundError`

- [ ] **Step 3: 写 scoring.py**

```python
# app/services/scoring.py
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
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_scoring.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/scoring.py tests/test_scoring.py
git commit -m "feat: scoring and advancement logic"
```

---

## Task 5: 编排——建赛、建首轮、持久化分组与站位

**Files:**
- Create: `app/services/tournament.py`
- Test: `tests/test_tournament.py`(追加)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_tournament.py 追加
from app.enums import Category, ProLevel, RaceFormat
from app.services import tournament as T, seasons as ssvc, cars as csvc
from sqlmodel import select
from app.models import RaceRound, Group, GroupMember, Heat, HeatResult


def _make_cars(session, n, category=Category.GT3):
    ids = []
    for i in range(n):
        c = csvc.create_car(session, nickname=f"车{i}", category=category,
                            brand="法拉利", casting="", description="", team_id=None)
        ids.append(c.id)
    return ids


def test_create_solo_race_builds_first_round(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 6)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    rounds = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).all()
    assert len(rounds) == 1 and rounds[0].number == 1
    groups = session.exec(select(Group).where(Group.round_id == rounds[0].id)).all()
    assert sorted(len(session.exec(select(GroupMember).where(
        GroupMember.group_id == grp.id)).all()) for grp in groups) == [3, 3]


def test_each_group_has_four_heats_with_lanes(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 4)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    grp = session.exec(select(Group)).first()
    heats = session.exec(select(Heat).where(Heat.group_id == grp.id)).all()
    assert len(heats) == 4
    h1 = sorted(heats, key=lambda h: h.number)[0]
    rows = session.exec(select(HeatResult).where(HeatResult.heat_id == h1.id)).all()
    assert sorted(r.lane for r in rows) == [1, 2, 3, 4]


def test_create_race_rejects_five_cars(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 5)
    import pytest
    from app.services.grouping import GroupingError
    with pytest.raises(GroupingError):
        T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                      format=RaceFormat.SOLO, car_ids=cars, seed=1)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_tournament.py -k "create_solo or four_heats or five_cars" -v`
Expected: FAIL

- [ ] **Step 3: 写 tournament.py(建赛 + 建轮)**

```python
# app/services/tournament.py
from typing import Optional
from sqlmodel import Session, select
from app.models import (Race, RaceEntry, RaceRound, Group, GroupMember,
                        Heat, HeatResult)
from app.enums import Category, ProLevel, RaceFormat, RaceStatus
from app.services import grouping, lineup, seasons as ssvc


def create_race(session: Session, *, category: Category, pro_level: ProLevel,
                format: RaceFormat, car_ids: list[int],
                seed: Optional[int] = None) -> Race:
    season = ssvc.get_active_season(session)
    if season is None:
        raise ValueError("没有进行中的赛季,请先开启赛季")
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
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_tournament.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/tournament.py tests/test_tournament.py
git commit -m "feat: create race and build first round"
```

---

## Task 6: 录入单场结果 + 撤销(回退)

**Files:**
- Modify: `app/services/tournament.py`
- Test: `tests/test_tournament.py`(追加)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_tournament.py 追加
def _record_group(session, group_id, order):
    """order: 每场 [道1车,道2车,...] 的名次按给定 car 顺序 1..k。这里简化为给每场同一名次顺序。"""
    from app.models import Heat
    heats = session.exec(select(Heat).where(Heat.group_id == group_id)
                         .order_by(Heat.number)).all()
    for h in heats:
        T.record_heat(session, h.id, ranks={car: pos + 1 for pos, car in enumerate(order)})


def test_record_heat_sets_ranks_and_recorded(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 4)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    grp = session.exec(select(Group)).first()
    h1 = session.exec(select(Heat).where(Heat.group_id == grp.id)
                      .order_by(Heat.number)).first()
    T.record_heat(session, h1.id, ranks={cars[0]: 1, cars[1]: 2, cars[2]: 3, cars[3]: 4})
    session.refresh(h1)
    assert h1.recorded is True
    rows = session.exec(select(HeatResult).where(HeatResult.heat_id == h1.id)).all()
    assert {r.car_id: r.rank for r in rows}[cars[0]] == 1


def test_undo_heat_clears_ranks(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 4)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    grp = session.exec(select(Group)).first()
    h1 = session.exec(select(Heat).where(Heat.group_id == grp.id)
                      .order_by(Heat.number)).first()
    T.record_heat(session, h1.id, ranks={cars[0]: 1, cars[1]: 2, cars[2]: 3, cars[3]: 4})
    T.undo_heat(session, h1.id)
    session.refresh(h1)
    assert h1.recorded is False
    rows = session.exec(select(HeatResult).where(HeatResult.heat_id == h1.id)).all()
    assert all(r.rank is None and r.dnf is False for r in rows)


def test_record_heat_with_dnf(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 4)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    grp = session.exec(select(Group)).first()
    h1 = session.exec(select(Heat).where(Heat.group_id == grp.id)
                      .order_by(Heat.number)).first()
    T.record_heat(session, h1.id, ranks={cars[0]: 1, cars[1]: 2, cars[2]: 3},
                  dnf={cars[3]})
    rows = session.exec(select(HeatResult).where(HeatResult.heat_id == h1.id)).all()
    by_car = {r.car_id: r for r in rows}
    assert by_car[cars[3]].dnf is True and by_car[cars[3]].rank is None
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_tournament.py -k "record_heat or undo" -v`
Expected: FAIL,`AttributeError: module ... has no attribute 'record_heat'`

- [ ] **Step 3: 在 tournament.py 追加 record_heat / undo_heat**

```python
# app/services/tournament.py 追加
def record_heat(session: Session, heat_id: int, *,
                ranks: dict[int, int], dnf: set[int] | None = None) -> None:
    dnf = dnf or set()
    heat = session.get(Heat, heat_id)
    rows = session.exec(select(HeatResult).where(HeatResult.heat_id == heat_id)).all()
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
    session.commit()
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_tournament.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/tournament.py tests/test_tournament.py
git commit -m "feat: record and undo heat results"
```

---

## Task 7: 小组结算、1V1 裁决、晋级与下一轮 / 决赛

**Files:**
- Modify: `app/services/tournament.py`
- Test: `tests/test_tournament.py`(追加)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_tournament.py 追加
from app.models import TieBreak


def _read_results(session, group_id):
    from app.models import Heat
    out: dict[int, list] = {}
    heats = session.exec(select(Heat).where(Heat.group_id == group_id)).all()
    for h in heats:
        for r in session.exec(select(HeatResult).where(HeatResult.heat_id == h.id)).all():
            out.setdefault(r.car_id, []).append(r.rank)
    return out


def test_group_advancement_no_tie(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 4)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    grp = session.exec(select(Group)).first()
    # 让 cars[0] 全 1、cars[1] 全 2、cars[2] 全 3、cars[3] 全 4
    heats = session.exec(select(Heat).where(Heat.group_id == grp.id)).all()
    for h in heats:
        T.record_heat(session, h.id,
                      ranks={cars[0]: 1, cars[1]: 2, cars[2]: 3, cars[3]: 4})
    adv = T.settle_group(session, grp.id)
    assert adv.advancers == [cars[0], cars[1]]


def test_group_tie_needs_decision_then_resolved(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 4)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    grp = session.exec(select(Group)).first()
    heats = sorted(session.exec(select(Heat).where(Heat.group_id == grp.id)).all(),
                   key=lambda h: h.number)
    # cars[0] 稳第一;cars[1] 与 cars[2] 打平争第二
    plans = [
        {cars[0]: 1, cars[1]: 2, cars[2]: 3, cars[3]: 4},
        {cars[0]: 1, cars[1]: 3, cars[2]: 2, cars[3]: 4},
        {cars[0]: 1, cars[1]: 2, cars[2]: 3, cars[3]: 4},
        {cars[0]: 1, cars[1]: 3, cars[2]: 2, cars[3]: 4},
    ]
    for h, p in zip(heats, plans):
        T.record_heat(session, h.id, ranks=p)
    adv = T.settle_group(session, grp.id)
    assert adv.advancers is None
    assert set(adv.tie_between) == {cars[1], cars[2]}
    T.resolve_tie(session, grp.id, winner_car_id=cars[2])
    adv2 = T.settle_group(session, grp.id)
    assert adv2.advancers == [cars[0], cars[2]]


def test_advance_to_next_round_until_final(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 6)   # 3,3 -> 晋级4 -> 决赛组4
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    # 录入所有第一轮小组,使每组前两名确定(用站位顺序当名次)
    r1 = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).first()
    for grp in session.exec(select(Group).where(Group.round_id == r1.id)).all():
        members = [m.car_id for m in session.exec(select(GroupMember)
                   .where(GroupMember.group_id == grp.id)).all()]
        for h in session.exec(select(Heat).where(Heat.group_id == grp.id)).all():
            T.record_heat(session, h.id,
                          ranks={c: i + 1 for i, c in enumerate(members)})
    result = T.advance_round(session, race.id, seed=2)
    assert result.kind == "next_round"
    rounds = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).all()
    assert len(rounds) == 2
    final = [r for r in rounds if r.number == 2][0]
    assert final.is_final is True


def test_final_round_produces_ranking_and_finishes(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 4)   # 直接就是决赛组
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    r1 = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).first()
    grp = session.exec(select(Group).where(Group.round_id == r1.id)).first()
    members = [m.car_id for m in session.exec(select(GroupMember)
               .where(GroupMember.group_id == grp.id)).all()]
    for h in session.exec(select(Heat).where(Heat.group_id == grp.id)).all():
        T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(members)})
    result = T.advance_round(session, race.id, seed=2)
    assert result.kind == "finished"
    assert result.ranking == members         # 名次 = 总分序
    from app.models import Race
    assert session.get(Race, race.id).status.value == "已结束"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_tournament.py -k "advancement or tie or advance or final" -v`
Expected: FAIL

- [ ] **Step 3: 在 tournament.py 追加结算/晋级逻辑**

```python
# app/services/tournament.py 追加
from dataclasses import dataclass
from app.models import TieBreak, Race
from app.enums import RaceStatus
from app.services import scoring


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
    rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race_id)
                       .order_by(RaceRound.number.desc())).first()
    groups = _round_groups(session, rnd.id)

    # 1) 所有小组必须录完
    not_done = [g.id for g in groups if not group_recorded(session, g.id)]
    if not_done:
        return AdvanceResult(kind="needs_results", pending_group_ids=not_done)

    # 2) 决赛轮:输出最终名次并结束
    if rnd.is_final:
        totals = scoring.group_totals(_group_results(session, groups[0].id))
        ranking = scoring.final_ranking(totals)
        race.status = RaceStatus.FINISHED
        session.add(race); session.commit()
        return AdvanceResult(kind="finished", ranking=ranking)

    # 3) 非决赛轮:逐组结算,遇未裁决并列则要求决断
    advancers: list[int] = []
    for g in groups:
        adv = settle_group(session, g.id)
        if adv.advancers is None:
            return AdvanceResult(kind="needs_decision", pending_group_ids=[g.id])
        advancers.extend(adv.advancers)

    # 4) 用晋级者建下一轮
    _build_round(session, race, number=rnd.number + 1, car_ids=advancers, seed=seed)
    return AdvanceResult(kind="next_round")
```

> 实现细节:`_build_round`、`Heat`、`HeatResult`、`Optional` 已在文件上方导入;`scoring`、`Race`、`RaceStatus`、`TieBreak`、`dataclass` 在本步导入。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_tournament.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/tournament.py tests/test_tournament.py
git commit -m "feat: group settle, tie-break, round advancement and final ranking"
```

---

## Task 8: 车队锦标赛(分组与结算差异)

**Files:**
- Modify: `app/services/tournament.py`(车队赛分支)
- Create: `app/services/team_scoring.py`
- Test: `tests/test_team_championship.py`

规则:每组 2 个车队(2-4 辆车);比车队总分;一队 1 车 vs 一队 2 车 → 1 车积分 ×2;车队总分并列 → 加赛 4 轮(本计划:标记 needs_decision 让用户加赛后再录;加赛实现为「为该组再建 4 场」)。

- [ ] **Step 1: 写失败测试(车队计分纯函数)**

```python
# tests/test_team_championship.py
from app.services import team_scoring as ts


def test_team_total_simple():
    # team_cars: team_id -> [car_ids];car_points: car -> 总分
    team_cars = {1: [10, 11], 2: [20, 21]}
    car_points = {10: 8, 11: 6, 20: 5, 21: 4}
    totals = ts.team_totals(team_cars, car_points)
    assert totals == {1: 14, 2: 9}


def test_single_car_team_doubled():
    team_cars = {1: [10], 2: [20, 21]}
    car_points = {10: 8, 20: 5, 21: 4}
    totals = ts.team_totals(team_cars, car_points)
    assert totals[1] == 16          # 8 * 2
    assert totals[2] == 9


def test_team_winner_no_tie():
    assert ts.team_winner({1: 16, 2: 9}) == 1


def test_team_tie_returns_none():
    assert ts.team_winner({1: 10, 2: 10}) is None
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_team_championship.py -v`
Expected: FAIL,`ModuleNotFoundError`

- [ ] **Step 3: 写 team_scoring.py**

```python
# app/services/team_scoring.py
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
```

- [ ] **Step 4: 写车队赛建组测试**

```python
# tests/test_team_championship.py 追加
from app.enums import Category, ProLevel, RaceFormat, TeamType
from app.services import tournament as T, seasons as ssvc, cars as csvc, teams as tsvc
from sqlmodel import select
from app.models import Group, GroupMember


def _team_with_cars(session, brand, n):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand=brand, name=None)
    ids = []
    for i in range(n):
        c = csvc.create_car(session, nickname=f"{brand}{i}", category=Category.GT3,
                            brand=brand, casting="", description="", team_id=t.id)
        ids.append(c.id)
    return t, ids


def test_team_race_groups_two_teams_each(session):
    ssvc.start_season(session, name="2026 S1")
    teams = []
    car_ids = []
    for b in ["法拉利", "保时捷", "奥迪", "宝马"]:
        t, ids = _team_with_cars(session, b, 2)
        teams.append(t.id); car_ids += ids
    race = T.create_team_race(session, category=Category.GT3,
                              pro_level=ProLevel.PRO, team_ids=teams, seed=1)
    grp = session.exec(select(Group)).first()
    assert grp.team_a_id is not None and grp.team_b_id is not None
    members = session.exec(select(GroupMember)
                           .where(GroupMember.group_id == grp.id)).all()
    assert len(members) == 4          # 两队各 2 车
```

- [ ] **Step 5: 运行确认失败**

Run: `pytest tests/test_team_championship.py -k team_race_groups -v`
Expected: FAIL,`AttributeError: ... 'create_team_race'`

- [ ] **Step 6: 在 tournament.py 追加 create_team_race**

```python
# app/services/tournament.py 追加
import random
from app.enums import RaceFormat


def _team_cars(session: Session, team_id: int, category: Category) -> list[int]:
    from app.models import Car
    return [c.id for c in session.exec(select(Car).where(
        Car.team_id == team_id, Car.category == category)).all()]


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
```

- [ ] **Step 7: 写车队组结算测试**

```python
# tests/test_team_championship.py 追加
from app.models import Heat, HeatResult


def test_team_group_settle_picks_winner_team(session):
    ssvc.start_season(session, name="2026 S1")
    t1, c1 = _team_with_cars(session, "法拉利", 2)
    t2, c2 = _team_with_cars(session, "保时捷", 2)
    race = T.create_team_race(session, category=Category.GT3,
                              pro_level=ProLevel.PRO, team_ids=[t1.id, t2.id], seed=1)
    grp = session.exec(select(Group)).first()
    members = [m.car_id for m in session.exec(select(GroupMember)
               .where(GroupMember.group_id == grp.id)).all()]
    # 让法拉利两车包揽前二
    fer = set(c1)
    for h in session.exec(select(Heat).where(Heat.group_id == grp.id)).all():
        ordered = [c for c in members if c in fer] + [c for c in members if c not in fer]
        T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(ordered)})
    winner = T.settle_team_group(session, grp.id)
    assert winner.winner_team_id == t1.id
```

- [ ] **Step 8: 运行确认失败 → 追加 settle_team_group**

Run: `pytest tests/test_team_championship.py -k settle -v`
Expected: FAIL

```python
# app/services/tournament.py 追加
from dataclasses import dataclass as _dc
from app.services import team_scoring


@_dc
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
```

- [ ] **Step 9: 运行确认通过**

Run: `pytest tests/test_team_championship.py -v`
Expected: PASS

- [ ] **Step 10: 提交**

```bash
git add app/services/team_scoring.py app/services/tournament.py tests/test_team_championship.py
git commit -m "feat: team championship grouping and settlement"
```

> 加赛(并列时再建 4 场)与车队赛多轮晋级的编排,沿用单人赛的 `advance_round` 模式:本计划在 UI 任务里,车队赛并列时提示用户「加赛 4 轮」并调用 `_build_heats` 给该组追加 4 场(`number` 接续)。该编排函数 `extend_team_group_with_replay(session, group_id)` 在 Task 9 路由前补上,测试见 `test_team_championship.py::test_replay_adds_four_heats`。

- [ ] **Step 11: 加赛函数 + 测试**

```python
# tests/test_team_championship.py 追加
def test_replay_adds_four_heats(session):
    ssvc.start_season(session, name="2026 S1")
    t1, c1 = _team_with_cars(session, "法拉利", 2)
    t2, c2 = _team_with_cars(session, "保时捷", 2)
    race = T.create_team_race(session, category=Category.GT3,
                              pro_level=ProLevel.PRO, team_ids=[t1.id, t2.id], seed=1)
    grp = session.exec(select(Group)).first()
    before = len(session.exec(select(Heat).where(Heat.group_id == grp.id)).all())
    T.extend_team_group_with_replay(session, grp.id)
    after = len(session.exec(select(Heat).where(Heat.group_id == grp.id)).all())
    assert after == before + 4
```

```python
# app/services/tournament.py 追加
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
```

Run: `pytest tests/test_team_championship.py -v`
Expected: PASS

```bash
git add app/services/tournament.py tests/test_team_championship.py
git commit -m "feat: team tie replay heats"
```

---

## Task 9: 赛事 UI——开始比赛、勾选、分组可视化、录入、回退

**Files:**
- Modify: `app/routers/races.py`(计划一已建占位需在 main.py 注册;若未注册则在此注册)
- Create: 模板 `races.html`、`race_new.html`、`race_detail.html`、`_group_card.html`、`_heat_entry.html`
- Modify: `app/main.py`(`app.include_router(races.router)`)
- Test: `tests/test_races_routes.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_races_routes.py
from fastapi.testclient import TestClient
from app.main import app
from app.services import seasons as ssvc, cars as csvc
from app.enums import Category
from sqlmodel import select
from app.models import Race, Group, Heat, HeatResult, GroupMember

client = TestClient(app)


def _cars(session, n):
    ids = []
    for i in range(n):
        c = csvc.create_car(session, nickname=f"车{i}", category=Category.GT3,
                            brand="法拉利", casting="", description="", team_id=None)
        ids.append(c.id)
    return ids


def test_new_race_page_lists_eligible_cars(engine, session):
    ssvc.start_season(session, name="2026 S1")
    _cars(session, 4)
    r = client.get("/races/new?category=GT3&pro_level=专业&format=单人锦标赛")
    assert r.status_code == 200 and "车0" in r.text


def test_pro_race_excludes_teamless_when_required(engine, session):
    # 由 UI 决定:专业赛勾选列表只列有车队的车 —— 这里验证服务层过滤
    from app.routers.races import eligible_cars
    ssvc.start_season(session, name="2026 S1")
    _cars(session, 4)             # 都无车队
    elig = eligible_cars(session, Category.GT3, pro=True)
    assert elig == []


def test_create_race_and_view_groups(engine, session):
    ssvc.start_season(session, name="2026 S1")
    ids = _cars(session, 6)
    r = client.post("/races", data={"category": "GT3", "pro_level": "表演",
        "format": "单人锦标赛", "car_ids": [str(i) for i in ids]},
        follow_redirects=False)
    assert r.status_code in (302, 303)
    race = session.exec(select(Race)).one()
    page = client.get(f"/races/{race.id}")
    assert "A 组" in page.text and "B 组" in page.text


def test_record_and_undo_via_route(engine, session):
    ssvc.start_season(session, name="2026 S1")
    ids = _cars(session, 4)
    client.post("/races", data={"category": "GT3", "pro_level": "表演",
        "format": "单人锦标赛", "car_ids": [str(i) for i in ids]})
    race = session.exec(select(Race)).one()
    grp = session.exec(select(Group)).first()
    h1 = session.exec(select(Heat).where(Heat.group_id == grp.id)
                      .order_by(Heat.number)).first()
    rows = session.exec(select(HeatResult).where(HeatResult.heat_id == h1.id)).all()
    data = {f"rank_{r.car_id}": str(i + 1) for i, r in enumerate(rows)}
    client.post(f"/races/{race.id}/heats/{h1.id}", data=data)
    session.refresh(h1); assert h1.recorded is True
    client.post(f"/races/{race.id}/heats/{h1.id}/undo")
    session.refresh(h1); assert h1.recorded is False
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_races_routes.py -v`
Expected: FAIL(404 / import 错误)

- [ ] **Step 3: 写 eligible_cars + races.py 路由(开始/创建/详情)**

```python
# app/routers/races.py
from typing import Optional
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from app.db import get_session
from app.models import Car, Race, RaceRound, Group, GroupMember, Heat, HeatResult
from app.enums import Category, ProLevel, RaceFormat
from app.services import tournament as T, seasons as ssvc
from app.routers.pages import templates

router = APIRouter()


def eligible_cars(session: Session, category: Category, *, pro: bool) -> list[Car]:
    stmt = select(Car).where(Car.category == category)
    cars = session.exec(stmt.order_by(Car.nickname)).all()
    if pro:                                 # 专业赛排除无车队的车
        cars = [c for c in cars if c.team_id is not None]
    return cars


@router.get("/races", response_class=HTMLResponse)
def races_page(request: Request, session: Session = Depends(get_session)):
    races = session.exec(select(Race).order_by(Race.id.desc())).all()
    return templates.TemplateResponse("races.html", {
        "request": request, "races": races,
        "active": ssvc.get_active_season(session)})


@router.get("/races/new", response_class=HTMLResponse)
def new_race(request: Request, category: str = "GT3", pro_level: str = "专业",
             format: str = "单人锦标赛", session: Session = Depends(get_session)):
    cat = Category(category)
    cars = eligible_cars(session, cat, pro=(pro_level == "专业"))
    return templates.TemplateResponse("race_new.html", {
        "request": request, "cars": cars, "category": category,
        "pro_level": pro_level, "format": format})


@router.post("/races")
def create_race(request: Request, category: str = Form(...),
                pro_level: str = Form(...), format: str = Form(...),
                car_ids: list[int] = Form(default=[]),
                session: Session = Depends(get_session)):
    try:
        race = T.create_race(session, category=Category(category),
                             pro_level=ProLevel(pro_level),
                             format=RaceFormat(format), car_ids=car_ids)
        return RedirectResponse(f"/races/{race.id}", status_code=303)
    except Exception as e:
        cat = Category(category)
        cars = eligible_cars(session, cat, pro=(pro_level == "专业"))
        return templates.TemplateResponse("race_new.html", {
            "request": request, "cars": cars, "category": category,
            "pro_level": pro_level, "format": format, "error": str(e)},
            status_code=200)


@router.get("/races/{race_id}", response_class=HTMLResponse)
def race_detail(race_id: int, request: Request,
                session: Session = Depends(get_session)):
    race = session.get(Race, race_id)
    rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race_id)
                       .order_by(RaceRound.number.desc())).first()
    groups = session.exec(select(Group).where(Group.round_id == rnd.id)).all()
    view = []
    names = {c.id: c.nickname for c in session.exec(select(Car)).all()}
    for g in groups:
        members = [names[m.car_id] for m in session.exec(select(GroupMember)
                   .where(GroupMember.group_id == g.id)).all()]
        heats = session.exec(select(Heat).where(Heat.group_id == g.id)
                             .order_by(Heat.number)).all()
        heat_views = []
        for h in heats:
            rows = session.exec(select(HeatResult).where(
                HeatResult.heat_id == h.id).order_by(HeatResult.lane)).all()
            heat_views.append({"heat": h, "rows": rows, "names": names})
        view.append({"group": g, "members": members, "heats": heat_views})
    return templates.TemplateResponse("race_detail.html", {
        "request": request, "race": race, "round": rnd, "groups": view,
        "names": names})


@router.post("/races/{race_id}/heats/{heat_id}")
def record_heat(race_id: int, heat_id: int, request: Request,
                session: Session = Depends(get_session)):
    # 表单字段:rank_<car_id>=名次;dnf_<car_id>=on
    import asyncio
    form = asyncio.run(request.form())
    ranks: dict[int, int] = {}
    dnf: set[int] = set()
    for k, v in form.items():
        if k.startswith("rank_") and v:
            ranks[int(k[5:])] = int(v)
        if k.startswith("dnf_"):
            dnf.add(int(k[4:]))
    T.record_heat(session, heat_id, ranks=ranks, dnf=dnf)
    return RedirectResponse(f"/races/{race_id}", status_code=303)


@router.post("/races/{race_id}/heats/{heat_id}/undo")
def undo_heat(race_id: int, heat_id: int,
              session: Session = Depends(get_session)):
    T.undo_heat(session, heat_id)
    return RedirectResponse(f"/races/{race_id}", status_code=303)
```

> 注意:`record_heat` 路由读取动态表单字段用同步 `request.form()` 在 def 路由里不可直接 await;改为 `async def` 更稳妥:

```python
@router.post("/races/{race_id}/heats/{heat_id}")
async def record_heat(race_id: int, heat_id: int, request: Request,
                      session: Session = Depends(get_session)):
    form = await request.form()
    ranks, dnf = {}, set()
    for k, v in form.items():
        if k.startswith("rank_") and v:
            ranks[int(k[5:])] = int(v)
        if k.startswith("dnf_"):
            dnf.add(int(k[4:]))
    T.record_heat(session, heat_id, ranks=ranks, dnf=dnf)
    return RedirectResponse(f"/races/{race_id}", status_code=303)
```

(采用 `async def` 版本,删除上面同步版本与 `import asyncio`。)

- [ ] **Step 4: 在 main.py 注册 races 路由**

```python
from app.routers import races  # noqa: E402
app.include_router(races.router)
```

- [ ] **Step 5: 写 races.html**

```html
<!-- app/templates/races.html -->
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h2>赛事</h2>
  {% if not active %}<p class="error">没有进行中的赛季,请先到「赛季」开启。</p>{% endif %}
  <form method="get" action="/races/new">
    <label>赛事等级</label>
    <select name="category"><option>F1</option><option selected>GT3</option><option>公路车</option></select>
    <label>专业水平</label>
    <select name="pro_level"><option>专业</option><option>表演</option></select>
    <label>赛制</label>
    <select name="format"><option>单人锦标赛</option><option>车队锦标赛</option></select>
    <div style="margin-top:12px"><button class="btn">开始新比赛</button></div>
  </form>
</div>
<div class="card">
  <h3>历史比赛</h3>
  {% for r in races %}
  <a class="row" href="/races/{{ r.id }}"><span style="flex:1">{{ r.category.value }} · {{ r.format.value }} · {{ r.pro_level.value }}</span><span class="tag">{{ r.status.value }}</span></a>
  {% else %}<p>暂无比赛</p>{% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 6: 写 race_new.html(勾选参赛车)**

```html
<!-- app/templates/race_new.html -->
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h2>选择参赛赛车 — {{ category }} · {{ format }} · {{ pro_level }}</h2>
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
  <form method="post" action="/races">
    <input type="hidden" name="category" value="{{ category }}">
    <input type="hidden" name="pro_level" value="{{ pro_level }}">
    <input type="hidden" name="format" value="{{ format }}">
    {% for c in cars %}
    <label style="display:flex;align-items:center;gap:8px">
      <input type="checkbox" name="car_ids" value="{{ c.id }}" style="width:auto"> {{ c.nickname }} <small>({{ c.brand }})</small>
    </label>
    {% else %}<p>没有符合条件的赛车</p>{% endfor %}
    <div style="margin-top:12px"><button class="btn">随机分组,开始!</button></div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 7: 写 _group_card.html + race_detail.html**

```html
<!-- app/templates/_group_card.html -->
<div class="card">
  <h3>{{ g.group.label }} 组</h3>
  <p><small>{{ g.members | join(" · ") }}</small></p>
  {% for hv in g.heats %}
  <div style="border-top:1px solid #eee;padding-top:8px;margin-top:8px">
    <strong>第 {{ hv.heat.number }} 场 {% if hv.heat.recorded %}✓{% endif %}</strong>
    <form method="post" action="/races/{{ race.id }}/heats/{{ hv.heat.id }}">
      <table style="width:100%">
        {% for r in hv.rows %}
        <tr>
          <td>{{ r.lane }} 道</td>
          <td>{{ hv.names[r.car_id] }}</td>
          <td><input name="rank_{{ r.car_id }}" type="number" min="1" max="4"
                     value="{{ r.rank or '' }}" style="width:60px"></td>
          <td><label style="display:inline"><input type="checkbox" name="dnf_{{ r.car_id }}" style="width:auto" {{ 'checked' if r.dnf else '' }}> 未完赛</label></td>
        </tr>
        {% endfor %}
      </table>
      <button class="btn" type="submit">确认本场</button>
    </form>
    <form method="post" action="/races/{{ race.id }}/heats/{{ hv.heat.id }}/undo" style="display:inline">
      <button class="btn" type="submit">撤销本场</button>
    </form>
  </div>
  {% endfor %}
</div>
```

```html
<!-- app/templates/race_detail.html -->
{% extends "base.html" %}
{% block content %}
<h2>{{ race.category.value }} · {{ race.format.value }} · {{ race.pro_level.value }}
  <span class="tag">{{ race.status.value }}</span></h2>
<p>第 {{ round.number }} 轮{% if round.is_final %} · 决赛{% endif %}</p>
{% for g in groups %}{% include "_group_card.html" %}{% endfor %}
{% if race.status.value == "进行中" %}
<form method="post" action="/races/{{ race.id }}/advance">
  <button class="btn">本轮录完,进入下一轮 / 出名次</button>
</form>
{% endif %}
{% endblock %}
```

- [ ] **Step 8: 运行确认通过**

Run: `pytest tests/test_races_routes.py -v`
Expected: PASS

- [ ] **Step 9: 提交**

```bash
git add app/routers/races.py app/main.py app/templates/races.html app/templates/race_new.html app/templates/race_detail.html app/templates/_group_card.html tests/test_races_routes.py
git commit -m "feat: race UI - start, group view, heat entry, undo"
```

---

## Task 10: 晋级/决赛路由 + 1V1 裁决 UI

**Files:**
- Modify: `app/routers/races.py`
- Modify: `app/templates/race_detail.html`(决断/结果展示)
- Test: `tests/test_races_routes.py`(追加)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_races_routes.py 追加
def _record_all(session, race_id):
    rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race_id)
                       .order_by(RaceRound.number.desc())).first()
    for g in session.exec(select(Group).where(Group.round_id == rnd.id)).all():
        members = [m.car_id for m in session.exec(select(GroupMember)
                   .where(GroupMember.group_id == g.id)).all()]
        for h in session.exec(select(Heat).where(Heat.group_id == g.id)).all():
            from app.services import tournament as T
            T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(members)})


def test_advance_creates_next_round(engine, session):
    from app.models import RaceRound
    ssvc.start_season(session, name="2026 S1")
    ids = _cars(session, 6)
    client.post("/races", data={"category": "GT3", "pro_level": "表演",
        "format": "单人锦标赛", "car_ids": [str(i) for i in ids]})
    race = session.exec(select(Race)).one()
    _record_all(session, race.id)
    r = client.post(f"/races/{race.id}/advance", follow_redirects=False)
    assert r.status_code in (302, 303)
    rounds = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).all()
    assert len(rounds) == 2


def test_advance_final_finishes_and_shows_ranking(engine, session):
    ssvc.start_season(session, name="2026 S1")
    ids = _cars(session, 4)
    client.post("/races", data={"category": "GT3", "pro_level": "表演",
        "format": "单人锦标赛", "car_ids": [str(i) for i in ids]})
    race = session.exec(select(Race)).one()
    _record_all(session, race.id)
    client.post(f"/races/{race.id}/advance")
    session.refresh(race)
    assert race.status.value == "已结束"
    page = client.get(f"/races/{race.id}")
    assert "冠军" in page.text or "最终名次" in page.text
```

(顶部需 `from app.models import RaceRound`。)

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_races_routes.py -k advance -v`
Expected: FAIL(404)

- [ ] **Step 3: 在 races.py 追加 advance / tie 路由**

```python
# app/routers/races.py 追加
from app.models import RaceRound
from app.services import tournament as T


@router.post("/races/{race_id}/advance")
def advance(race_id: int, request: Request,
            session: Session = Depends(get_session)):
    result = T.advance_round(session, race_id)
    if result.kind == "finished":
        # 把最终名次暂存到查询参数,详情页读取
        ids = ",".join(str(i) for i in result.ranking)
        return RedirectResponse(f"/races/{race_id}?ranking={ids}", status_code=303)
    if result.kind == "needs_decision":
        gid = result.pending_group_ids[0]
        return RedirectResponse(f"/races/{race_id}/tie/{gid}", status_code=303)
    return RedirectResponse(f"/races/{race_id}", status_code=303)


@router.get("/races/{race_id}/tie/{group_id}", response_class=HTMLResponse)
def tie_page(race_id: int, group_id: int, request: Request,
             session: Session = Depends(get_session)):
    adv = T.settle_group(session, group_id)
    names = {c.id: c.nickname for c in session.exec(select(Car)).all()}
    return templates.TemplateResponse("race_tie.html", {
        "request": request, "race_id": race_id, "group_id": group_id,
        "tied": adv.tie_between, "names": names})


@router.post("/races/{race_id}/tie/{group_id}")
def resolve_tie(race_id: int, group_id: int, winner_car_id: int = Form(...),
                session: Session = Depends(get_session)):
    T.resolve_tie(session, group_id, winner_car_id=winner_car_id)
    return RedirectResponse(f"/races/{race_id}/advance" if False else
                            f"/races/{race_id}", status_code=303)
```

> 裁决后用户再次点「进入下一轮」即可;为简化,resolve_tie 后回详情页。

- [ ] **Step 4: 写 race_tie.html**

```html
<!-- app/templates/race_tie.html -->
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h2>并列,需要 1V1</h2>
  <p>以下赛车总分并列,争夺最后一个晋级名额,请选择本场 1V1 的胜者:</p>
  <form method="post" action="/races/{{ race_id }}/tie/{{ group_id }}">
    {% for cid in tied %}
    <label style="display:flex;gap:8px"><input type="radio" name="winner_car_id" value="{{ cid }}" style="width:auto" required> {{ names[cid] }}</label>
    {% endfor %}
    <div style="margin-top:12px"><button class="btn">确定胜者</button></div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 5: race_detail.html 展示最终名次**

在 `race_detail.html` 顶部 `<h2>` 之后插入:

```html
{% if request.query_params.get("ranking") %}
<div class="card">
  <h3>最终名次</h3>
  <ol>
    {% for cid in request.query_params.get("ranking").split(",") %}
    <li>{{ names[cid|int] }}{% if loop.index == 1 %} — 冠军{% endif %}</li>
    {% endfor %}
  </ol>
</div>
{% endif %}
```

- [ ] **Step 6: 运行确认通过**

Run: `pytest tests/test_races_routes.py -v`
Expected: PASS

- [ ] **Step 7: 全量回归 + 提交**

Run: `pytest -v`
Expected: 全部 PASS

```bash
git add app/routers/races.py app/templates/race_tie.html app/templates/race_detail.html tests/test_races_routes.py
git commit -m "feat: advancement, final ranking and 1v1 tie UI"
```

---

## 自检(写计划后已核对)

- **Spec 覆盖**:开始比赛+三选项(Task 9)、勾选参赛车且专业赛排除无车队(Task 9 `eligible_cars`)、随机分组铁律 3-4(Task 2)、站位每车遍历每道(Task 3)、计分 5/3/2/1 与 DNF(Task 4)、录入+回退(Task 6/9)、前 2 晋级与 2/3 名 1V1(Task 4/7/10)、重组到决赛组直接定名次(Task 7)、车队赛每组 2 队 + 1 车×2 + 并列加赛(Task 8)。
- **占位扫描**:无 TODO;`record_heat` 同步/异步两版本已明确「采用 async 版」。车队赛多轮晋级 UI 复用单人 advance 模式,已在 Task 8 备注与 `extend_team_group_with_replay`(Task 8 Step 11)落实算法层。
- **类型一致**:`create_race`/`create_team_race`/`record_heat`/`undo_heat`/`settle_group`/`resolve_tie`/`advance_round`/`settle_team_group`/`extend_team_group_with_replay` 在定义、测试、路由中签名一致;`AdvanceResult.kind` 取值集合在算法与路由分支一致("needs_results"/"needs_decision"/"next_round"/"finished")。
- **跨计划接口**:`advance_round` 的 "finished" 分支与 MMR/车队积分结算挂钩点留给计划三(在结算名次后调用钩子)。
