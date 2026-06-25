# 转会市场 · 计划A:经济基础 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> 依据 spec:`docs/superpowers/specs/2026-06-25-transfer-market-design.md`。前置:计划一~三已完成(现网 154+ 测试通过)。

**Goal:** 落地转会市场的经济基础——重定义车队积分规则、给赛车加合同属性、实现薪资/预算计算与赛季快照,并在页面展示。不含市场流程本身(计划B)。

**Architecture:** 把"从一场已结束比赛推导战绩"的逻辑收敛到纯函数模块 `racestats`;车队积分、薪资、预算各自独立服务,便于单测。沿用现有 `app/db.py::sync_schema` 自动加列、`CarSeasonMMR` 快照、`Jinja2` 页面。

**Tech Stack:** 同项目(Python3.9 + FastAPI + SQLModel + Jinja2;每个 .py 首行 `from __future__ import annotations`)。

---

## 文件结构
```
app/enums.py                      # 改:加 ContractType
app/config.py                     # 改:经济常数(替换旧 SOLO/TEAM_TEAM_POINTS)
app/models.py                     # 改:Car.contract;新表 TeamBudget / CarSalary
app/services/racestats.py         # 新:从已结束比赛推导晋级/名次/冠军/决赛圈(单人+车队)
app/services/team_points.py       # 新:新规则车队积分(替换 standings.award_solo/award_team)
app/services/salary.py            # 新:赛车薪资计算(赛季聚合 + MMR + 名宿)
app/services/budget.py            # 新:车队预算计算
app/services/market_snapshot.py   # 新:转会开盘时写入 TeamBudget/CarSalary 快照
app/services/tournament.py        # 改:advance_round 改调 team_points
app/routers/cars.py / teams.py    # 改:车页显示薪资/合同;队页显示预算;car_form 加合同选择
tests/test_racestats.py, test_team_points.py, test_salary.py, test_budget.py, test_market_snapshot.py
```

---

## Task 1: 枚举、常数、数据模型

**Files:** Modify `app/enums.py`, `app/config.py`, `app/models.py`;Test `tests/test_salary.py`(建表冒烟)

- [ ] **Step 1: enums 加合同类型**(`app/enums.py` 末尾,文件首行已有 future import)
```python
class ContractType(str, Enum):
    LONG = "长期"
    SHORT = "短期"
```

- [ ] **Step 2: config 经济常数**——删除旧的 `SOLO_TEAM_POINTS` / `TEAM_TEAM_POINTS`,新增:
```python
# 车队积分(新规则用,见 team_points.py)
TP_ADVANCE = 1          # 每次小组赛晋级
TP_PODIUM = {1: 4, 2: 2, 3: 1}   # 冠/亚/季额外
TP_TEAM_MULTIPLIER = 2  # 车队赛全部 ×2
# 预算
BUDGET_BASE = 800
POINT_VALUE = 20        # 每 1 车队积分 → 预算
CHAMP_BUDGET_SOLO = 50
CHAMP_BUDGET_TEAM = 100
# 薪资
SALARY_BASE = 100
SALARY_FLOOR = 30
SALARY_MMR_UP = 1.0     # MMR≥1500 每分
SALARY_MMR_DOWN = 0.5   # MMR<1500 每分(折扣)
SALARY_CHAMP = 100      # 每个夺冠
SALARY_FINALS = 40      # 每次进决赛圈未夺冠
SALARY_LEGEND = 100     # 名宿费
LEGEND_TOP_PCT = 0.10   # 历史 MMR 本类别前 10% 为名宿
```
> 注:`standings.py` 仍 import `SOLO_TEAM_POINTS/TEAM_TEAM_POINTS`——本任务删常数后会 import 失败,Task 3 会重写 standings 的发放函数;为保持每步可运行,**本步同时**把 `app/services/standings.py` 里 `award_solo`/`award_team` 函数体临时改为 `pass`(占位),并从 import 行移除这两个常数。Task 3 再补真逻辑。

- [ ] **Step 3: models 加合同与快照表**(`app/models.py`)
Car 类增字段:
```python
    contract: Optional[ContractType] = None   # 仅有车队时有意义
```
(顶部 import 改为 `from app.enums import Category, TeamType, SeasonStatus, CarStatus, ContractType`)
文件末尾加两表:
```python
class TeamBudget(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    season_id: int = Field(foreign_key="season.id")
    team_id: int = Field(foreign_key="team.id")
    budget: int

class CarSalary(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    season_id: int = Field(foreign_key="season.id")
    car_id: int = Field(foreign_key="car.id")
    salary: int
```

- [ ] **Step 4: 冒烟测试**(`tests/test_salary.py`,首行 future import)
```python
from app.models import TeamBudget, CarSalary, Car
from app.enums import ContractType


def test_new_tables_and_contract(session):
    from app.enums import Category
    c = Car(nickname="x", category=Category.GT3, contract=ContractType.LONG)
    session.add(c); session.commit(); session.refresh(c)
    assert c.contract == ContractType.LONG
    session.add(TeamBudget(season_id=1, team_id=1, budget=800))
    session.add(CarSalary(season_id=1, car_id=c.id, salary=150))
    session.commit()
```

- [ ] **Step 5:** `pytest tests/test_salary.py -v` → PASS;再跑全量 `pytest`,确认仅与 award 相关的 standings 测试需要 Task 3 修(其余应通过)。若 standings 测试因占位 `pass` 失败,**标记为 Task 3 处理**,本步只确认无 import 错误。

- [ ] **Step 6: 提交** `git add -A && git commit -m "feat(market): contract type, economy constants, budget/salary tables"`

---

## Task 2: racestats —— 从已结束比赛推导战绩(纯读)

**Files:** Create `app/services/racestats.py`;Test `tests/test_racestats.py`

定义(单人):某车**晋级次数 = 它出现过的轮数 − 1**;**名次**取决赛轮该组 `scoring.final_ranking`;**冠军** = 决赛名次第1;**进决赛圈** = 出现在决赛轮。车队赛同理但以"车队是否出现在某轮的组里"为单位。

- [ ] **Step 1: 失败测试**(`tests/test_racestats.py`)
```python
from sqlmodel import select
from app.enums import Category, ProLevel, RaceFormat, TeamType
from app.services import seasons as ssvc, teams as tsvc, cars as csvc, tournament as T
from app.services import racestats
from app.models import Race, RaceRound, Group, GroupMember, Heat


def _run_solo_6(session):
    ssvc.start_season(session, name="S1")
    ids = []
    for i in range(6):
        t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name=f"q{i}")
        ids.append(csvc.create_car(session, nickname=f"c{i}", category=Category.GT3,
                   brand="B", casting="", description="", team_id=t.id).id)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=ids, seed=1)
    # 逐轮按"组内成员顺序即名次"录完,直到结束
    while True:
        rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)
                           .order_by(RaceRound.number.desc())).first()
        for g in session.exec(select(Group).where(Group.round_id == rnd.id)).all():
            members = [m.car_id for m in session.exec(select(GroupMember)
                       .where(GroupMember.group_id == g.id)).all()]
            for h in session.exec(select(Heat).where(Heat.group_id == g.id)).all():
                T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(members)})
        res = T.advance_round(session, race.id, seed=2)
        if res.kind == "finished":
            return race, ids, res.ranking


def test_advancements_and_champion(session):
    race, ids, ranking = _run_solo_6(session)
    adv = racestats.car_advancements(session, race.id)   # car_id -> 晋级次数
    champ = ranking[0]
    # 6 车:3/3 -> 晋级4 -> 决赛组4。冠军至少晋级 1 次(从首轮),且 ≥ 末位
    assert adv[champ] >= 1
    ach = racestats.car_achievements(session, race.id)    # car_id -> {champion,finalist}
    assert ach[champ]["champion"] is True
    assert ach[champ]["finalist"] is True
    # 决赛圈应有 3-4 车 finalist
    assert sum(1 for v in ach.values() if v["finalist"]) in (3, 4)
```

- [ ] **Step 2:** `pytest tests/test_racestats.py -v` → FAIL(ModuleNotFoundError)。

- [ ] **Step 3: 写 `app/services/racestats.py`**
```python
from sqlmodel import Session, select
from app.models import RaceRound, Group, GroupMember, HeatResult, Heat, Race
from app.enums import RaceFormat
from app.services import scoring


def _rounds(session: Session, race_id: int):
    return session.exec(select(RaceRound).where(RaceRound.race_id == race_id)
                        .order_by(RaceRound.number)).all()


def _group_results(session: Session, group_id: int) -> dict:
    out: dict[int, list] = {}
    for h in session.exec(select(Heat).where(Heat.group_id == group_id)).all():
        for r in session.exec(select(HeatResult).where(HeatResult.heat_id == h.id)).all():
            out.setdefault(r.car_id, []).append(r.rank)
    return out


def car_appearances(session: Session, race_id: int) -> dict:
    """car_id -> 出现过的轮号集合。"""
    appear: dict[int, set] = {}
    for rnd in _rounds(session, race_id):
        for g in session.exec(select(Group).where(Group.round_id == rnd.id)).all():
            for m in session.exec(select(GroupMember)
                                  .where(GroupMember.group_id == g.id)).all():
                appear.setdefault(m.car_id, set()).add(rnd.number)
    return appear


def car_advancements(session: Session, race_id: int) -> dict:
    return {cid: len(rs) - 1 for cid, rs in car_appearances(session, race_id).items()}


def final_group(session: Session, race_id: int):
    rnd = _rounds(session, race_id)[-1]
    return session.exec(select(Group).where(Group.round_id == rnd.id)).first()


def final_ranking(session: Session, race_id: int) -> list:
    g = final_group(session, race_id)
    totals = scoring.group_totals(_group_results(session, g.id))
    return scoring.final_ranking(totals)


def car_achievements(session: Session, race_id: int) -> dict:
    """car_id -> {champion: bool, finalist: bool}。"""
    fg = final_group(session, race_id)
    finalists = {m.car_id for m in session.exec(select(GroupMember)
                 .where(GroupMember.group_id == fg.id)).all()}
    ranking = final_ranking(session, race_id)
    champ = ranking[0] if ranking else None
    out = {}
    for cid in car_appearances(session, race_id):
        out[cid] = {"champion": cid == champ, "finalist": cid in finalists}
    return out


def car_podium(session: Session, race_id: int) -> dict:
    """car_id -> 名次(1/2/3),仅决赛圈前三;其余不在 dict。"""
    ranking = final_ranking(session, race_id)
    return {cid: i + 1 for i, cid in enumerate(ranking[:3])}
```

- [ ] **Step 4:** `pytest tests/test_racestats.py -v` → PASS。

- [ ] **Step 5: 提交** `git add app/services/racestats.py tests/test_racestats.py && git commit -m "feat(market): racestats - advancements/podium/champion/finalist"`

---

## Task 3: 新车队积分规则 + 接回 advance_round

**Files:** Create `app/services/team_points.py`;Modify `app/services/standings.py`(发放改用新逻辑)、`app/services/tournament.py`(调用点);Test `tests/test_team_points.py`、修 `tests/test_standings.py`

规则:车队积分 = Σ该队车的(晋级×1 + 决赛圈名次 4/2/1);车队赛整体 ×2。发放仍写入现有 `TeamPointEntry`(来源记录),由 advance_round 在比赛结束时调用。

- [ ] **Step 1: 失败测试**(`tests/test_team_points.py`)
```python
from sqlmodel import select
from app.enums import Category, ProLevel, RaceFormat, TeamType
from app.services import (seasons as ssvc, teams as tsvc, cars as csvc,
                          tournament as T, team_points as tp, standings as st)
from app.models import Race, RaceRound, Group, GroupMember, Heat, TeamPointEntry


def _run_solo_4(session):
    s = ssvc.start_season(session, name="S1")
    teams, ids = [], []
    for i in range(4):
        t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name=f"q{i}")
        teams.append(t.id)
        ids.append(csvc.create_car(session, nickname=f"c{i}", category=Category.GT3,
                   brand="B", casting="", description="", team_id=t.id).id)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=ids, seed=1)
    rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).first()
    grp = session.exec(select(Group).where(Group.round_id == rnd.id)).first()
    members = [m.car_id for m in session.exec(select(GroupMember)
               .where(GroupMember.group_id == grp.id)).all()]
    for h in session.exec(select(Heat).where(Heat.group_id == grp.id)).all():
        T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(members)})
    return s, race, teams, ids


def test_solo_champion_team_points(session):
    s, race, teams, ids = _run_solo_4(session)
    result = T.advance_round(session, race.id)          # 4 车直接是决赛组
    assert result.kind == "finished"
    champ_car = result.ranking[0]
    champ_team = session.get(__import__('app.models', fromlist=['Car']).Car, champ_car).team_id
    # 4 车决赛组:无晋级(只有 1 轮),冠军 = 决赛名次1 → +4
    pts = st.team_season_points(session, champ_team, s.id)
    assert pts == 4
    # 第2名队 +2,第3名队 +1,第4名队 0
    second_team = session.get(__import__('app.models', fromlist=['Car']).Car, result.ranking[1]).team_id
    assert st.team_season_points(session, second_team, s.id) == 2
```

- [ ] **Step 2:** `pytest tests/test_team_points.py -v` → FAIL。

- [ ] **Step 3: 写 `app/services/team_points.py`**
```python
from sqlmodel import Session, select
from app.models import Race, RaceEntry, TeamPointEntry, Car
from app.enums import RaceFormat
from app.config import TP_ADVANCE, TP_PODIUM, TP_TEAM_MULTIPLIER
from app.services import racestats


def _car_team(session: Session, race_id: int, car_id: int):
    e = session.exec(select(RaceEntry).where(RaceEntry.race_id == race_id,
                     RaceEntry.car_id == car_id)).first()
    return e.team_id if e else None


def car_points(session: Session, race_id: int) -> dict:
    """car_id -> 该车在本场赚到的车队积分(晋级 + 决赛圈名次)。"""
    adv = racestats.car_advancements(session, race_id)
    podium = racestats.car_podium(session, race_id)
    pts = {}
    for cid, a in adv.items():
        pts[cid] = a * TP_ADVANCE + TP_PODIUM.get(podium.get(cid), 0)
    return pts


def award(session: Session, race: Race) -> None:
    """把本场车队积分写入 TeamPointEntry(来源记录)。"""
    mult = TP_TEAM_MULTIPLIER if race.format == RaceFormat.TEAM else 1
    by_team: dict[int, int] = {}
    sources: dict[int, list] = {}
    for cid, p in car_points(session, race.id).items():
        if p == 0:
            continue
        tid = _car_team(session, race.id, cid)
        if tid is None:
            continue
        by_team[tid] = by_team.get(tid, 0) + p * mult
        nick = session.get(Car, cid).nickname
        sources.setdefault(tid, []).append(f"{nick} +{p * mult}")
    for tid, total in by_team.items():
        desc = race.format.value + ":" + "、".join(sources[tid])
        session.add(TeamPointEntry(season_id=race.season_id, team_id=tid,
                    points=total, source_car_id=None, race_id=race.id, description=desc))
    session.commit()
```

- [ ] **Step 4: 重写 standings 发放**——`app/services/standings.py`:把 Task1 占位的 `award_solo`/`award_team` 删除,改为薄封装(保留旧调用名以兼容,但都转调 team_points.award)。在 `standings.py` 加:
```python
from app.services import team_points

def award_race(session, race):
    team_points.award(session, race)
```
并删除 `award_solo`/`award_team` 及其对 `SOLO_TEAM_POINTS/TEAM_TEAM_POINTS` 的引用。

- [ ] **Step 5: 改 advance_round 调用点**——`app/services/tournament.py` 决赛 `finished` 分支里,原来按 `RaceFormat` 调 `st_svc.award_solo/award_team` 的代码,替换为:
```python
        if race.pro_level == ProLevel.PRO:
            st_svc.award_race(session, race)
```
(删除 `_team_final_ranking` 的发放用途调用;该函数若不再被用可保留或删。)

- [ ] **Step 6: 修旧测试**——`tests/test_standings.py` 中断言 `award_solo/award_team` 旧分值(5/4/3、10/8/6)的用例:改为通过跑完整比赛后用 `team_season_points` 断言新规则结果(参考 Task3 Step1 写法),或删除针对旧函数的直接单测、保留 `team_board`/`team_season_points` 查询测试。`tests/test_honors_integration.py` 里断言 `+5`/`+10` 的也同样改为新规则期望值。

- [ ] **Step 7:** `pytest tests/test_team_points.py tests/test_standings.py tests/test_honors_integration.py -v` → PASS;再 `pytest` 全量确认无回归。

- [ ] **Step 8: 提交** `git add -A && git commit -m "feat(market): new team-points rule (advance+podium, team x2)"`

---

## Task 4: 薪资计算

**Files:** Create `app/services/salary.py`;Test `tests/test_salary.py`(追加)

薪资按**赛季聚合**:遍历该赛季该车参加过的所有专业赛,累计夺冠/进决赛圈次数;MMR 用 `CarSeasonMMR` 快照(无则用 `Car.season_mmr`);名宿看 `Car.historical_mmr` 本类别前 10%。

- [ ] **Step 1: 失败测试**(追加到 `tests/test_salary.py`)
```python
from app.services import salary as sal
from app.config import SALARY_BASE


def test_salary_mid_car(session):
    from app.enums import Category
    from app.models import Car
    c = Car(nickname="mid", category=Category.GT3, season_mmr=1500, historical_mmr=1500)
    session.add(c); session.commit(); session.refresh(c)
    # 无比赛、MMR1500、非名宿 → 基础 100
    assert sal.compute_salary(session, c, season_id=1) == SALARY_BASE


def test_salary_below_1500_discount(session):
    from app.enums import Category
    from app.models import Car
    c = Car(nickname="bad", category=Category.GT3, season_mmr=1430, historical_mmr=1430)
    session.add(c); session.commit(); session.refresh(c)
    # 1430:折扣 (1500-1430)*0.5=35 → 100-35=65
    assert sal.compute_salary(session, c, season_id=1) == 65


def test_salary_floor(session):
    from app.enums import Category
    from app.models import Car
    c = Car(nickname="terrible", category=Category.GT3, season_mmr=1200, historical_mmr=1200)
    session.add(c); session.commit(); session.refresh(c)
    # 100 - 150 = -50 → 下限 30
    assert sal.compute_salary(session, c, season_id=1) == 30
```

- [ ] **Step 2:** `pytest tests/test_salary.py -v` → FAIL(no compute_salary)。

- [ ] **Step 3: 写 `app/services/salary.py`**
```python
import math
from sqlmodel import Session, select
from app.models import Car, Race, RaceEntry, CarSeasonMMR
from app.enums import ProLevel
from app.config import (SALARY_BASE, SALARY_FLOOR, SALARY_MMR_UP, SALARY_MMR_DOWN,
                        SALARY_CHAMP, SALARY_FINALS, SALARY_LEGEND, LEGEND_TOP_PCT)
from app.services import racestats


def _season_mmr(session: Session, car: Car, season_id: int) -> float:
    snap = session.exec(select(CarSeasonMMR).where(
        CarSeasonMMR.season_id == season_id, CarSeasonMMR.car_id == car.id)).first()
    return snap.mmr if snap else car.season_mmr


def _mmr_component(mmr: float) -> int:
    if mmr >= 1500:
        return round((mmr - 1500) * SALARY_MMR_UP)
    return -round((1500 - mmr) * SALARY_MMR_DOWN)


def is_legend(session: Session, car: Car) -> bool:
    peers = session.exec(select(Car).where(Car.category == car.category)).all()
    if not peers:
        return False
    ordered = sorted(peers, key=lambda c: c.historical_mmr, reverse=True)
    cutoff = max(1, math.ceil(len(ordered) * LEGEND_TOP_PCT))
    top_ids = {c.id for c in ordered[:cutoff]}
    return car.id in top_ids


def _season_achievements(session: Session, car: Car, season_id: int):
    champ, finals = 0, 0
    races = session.exec(select(Race).where(Race.season_id == season_id,
                         Race.pro_level == ProLevel.PRO)).all()
    for race in races:
        entry = session.exec(select(RaceEntry).where(
            RaceEntry.race_id == race.id, RaceEntry.car_id == car.id)).first()
        if entry is None:
            continue
        ach = racestats.car_achievements(session, race.id).get(car.id)
        if not ach:
            continue
        if ach["champion"]:
            champ += 1
        elif ach["finalist"]:
            finals += 1
    return champ, finals


def compute_salary(session: Session, car: Car, season_id: int) -> int:
    mmr = _season_mmr(session, car, season_id)
    champ, finals = _season_achievements(session, car, season_id)
    raw = (SALARY_BASE + _mmr_component(mmr)
           + SALARY_CHAMP * champ + SALARY_FINALS * finals
           + (SALARY_LEGEND if is_legend(session, car) else 0))
    return max(SALARY_FLOOR, raw)
```

- [ ] **Step 4:** `pytest tests/test_salary.py -v` → PASS。

- [ ] **Step 5: 提交** `git add app/services/salary.py tests/test_salary.py && git commit -m "feat(market): car salary computation"`

---

## Task 5: 预算计算

**Files:** Create `app/services/budget.py`;Test `tests/test_budget.py`

预算 = 800 + 20×该队赛季积分 + 50×单人赛冠军次数 + 100×车队赛冠军次数(冠军次数从该赛季比赛战绩推得)。

- [ ] **Step 1: 失败测试**(`tests/test_budget.py`)
```python
from sqlmodel import select
from app.enums import Category, ProLevel, RaceFormat, TeamType
from app.services import (seasons as ssvc, teams as tsvc, cars as csvc,
                          tournament as T, standings as st, budget as bud)
from app.models import Race, RaceRound, Group, GroupMember, Heat, Car
from app.config import BUDGET_BASE


def test_budget_base_for_no_history(session):
    s = ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    assert bud.compute_budget(session, t, s.id) == BUDGET_BASE


def test_budget_with_points_and_solo_champion(session):
    s = ssvc.start_season(session, name="S1")
    teams, ids = [], []
    for i in range(4):
        t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name=f"q{i}")
        teams.append(t); ids.append(csvc.create_car(session, nickname=f"c{i}",
            category=Category.GT3, brand="B", casting="", description="", team_id=t.id).id)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=ids, seed=1)
    rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).first()
    grp = session.exec(select(Group).where(Group.round_id == rnd.id)).first()
    members = [m.car_id for m in session.exec(select(GroupMember)
               .where(GroupMember.group_id == grp.id)).all()]
    for h in session.exec(select(Heat).where(Heat.group_id == grp.id)).all():
        T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(members)})
    res = T.advance_round(session, race.id)
    champ_team_id = session.get(Car, res.ranking[0]).team_id
    champ_team = session.get(__import__('app.models', fromlist=['Team']).Team, champ_team_id)
    # 冠军队:积分4 → 800 + 20*4 + 50(单人冠军) = 930
    assert bud.compute_budget(session, champ_team, s.id) == 800 + 80 + 50
```

- [ ] **Step 2:** `pytest tests/test_budget.py -v` → FAIL。

- [ ] **Step 3: 写 `app/services/budget.py`**
```python
from sqlmodel import Session, select
from app.models import Team, Race, RaceEntry, Car
from app.enums import ProLevel, RaceFormat
from app.config import (BUDGET_BASE, POINT_VALUE, CHAMP_BUDGET_SOLO, CHAMP_BUDGET_TEAM)
from app.services import standings, racestats


def _championships(session: Session, team: Team, season_id: int):
    """返回 (单人赛夺冠次数, 车队赛夺冠次数) —— 该队的车在该赛季夺冠的比赛。"""
    solo, team_cnt = 0, 0
    races = session.exec(select(Race).where(Race.season_id == season_id,
                         Race.pro_level == ProLevel.PRO)).all()
    for race in races:
        ranking = racestats.final_ranking(session, race.id)
        if not ranking:
            continue
        champ_car = ranking[0]
        entry = session.exec(select(RaceEntry).where(
            RaceEntry.race_id == race.id, RaceEntry.car_id == champ_car)).first()
        if entry and entry.team_id == team.id:
            if race.format == RaceFormat.TEAM:
                team_cnt += 1
            else:
                solo += 1
    return solo, team_cnt


def compute_budget(session: Session, team: Team, season_id: int) -> int:
    pts = standings.team_season_points(session, team.id, season_id)
    solo, team_cnt = _championships(session, team, season_id)
    return (BUDGET_BASE + POINT_VALUE * pts
            + CHAMP_BUDGET_SOLO * solo + CHAMP_BUDGET_TEAM * team_cnt)
```

- [ ] **Step 4:** `pytest tests/test_budget.py -v` → PASS。

- [ ] **Step 5: 提交** `git add app/services/budget.py tests/test_budget.py && git commit -m "feat(market): team budget computation"`

---

## Task 6: 快照写入 + 页面展示 + 合同编辑

**Files:** Create `app/services/market_snapshot.py`;Modify `app/routers/cars.py`、`app/routers/teams.py`、`app/templates/car_detail.html`、`app/templates/team_detail.html`、`app/templates/car_form.html`;Test `tests/test_market_snapshot.py`

- [ ] **Step 1: 失败测试**(`tests/test_market_snapshot.py`)
```python
from sqlmodel import select
from app.enums import Category, TeamType
from app.services import seasons as ssvc, teams as tsvc, cars as csvc
from app.services import market_snapshot as ms
from app.models import TeamBudget, CarSalary


def test_snapshot_writes_budget_and_salary(session):
    s = ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    csvc.create_car(session, nickname="c", category=Category.GT3, brand="B",
                    casting="", description="", team_id=t.id)
    ms.snapshot_season(session, s.id)
    assert session.exec(select(TeamBudget).where(TeamBudget.season_id == s.id)).all()
    assert session.exec(select(CarSalary).where(CarSalary.season_id == s.id)).all()
```

- [ ] **Step 2:** `pytest tests/test_market_snapshot.py -v` → FAIL。

- [ ] **Step 3: 写 `app/services/market_snapshot.py`**
```python
from sqlmodel import Session, select
from app.models import Team, Car, TeamBudget, CarSalary
from app.services import budget as bud, salary as sal


def snapshot_season(session: Session, season_id: int) -> None:
    """为某赛季写入各队预算、各车薪资快照(转会开盘时调用,可重复:先清后写)。"""
    for row in session.exec(select(TeamBudget).where(TeamBudget.season_id == season_id)).all():
        session.delete(row)
    for row in session.exec(select(CarSalary).where(CarSalary.season_id == season_id)).all():
        session.delete(row)
    session.commit()
    for t in session.exec(select(Team)).all():
        session.add(TeamBudget(season_id=season_id, team_id=t.id,
                    budget=bud.compute_budget(session, t, season_id)))
    for c in session.exec(select(Car)).all():
        session.add(CarSalary(season_id=season_id, car_id=c.id,
                    salary=sal.compute_salary(session, c, season_id)))
    session.commit()
```

- [ ] **Step 4:** `pytest tests/test_market_snapshot.py -v` → PASS。

- [ ] **Step 5: 合同选择加进 car_form**(`app/templates/car_form.html`,在"所属车队"下面加):
```html
    <label>合同(有车队时有效)</label>
    <select name="contract">
      <option value="" {{ "selected" if not (car and car.contract) else "" }}>—(短期默认)</option>
      <option value="长期" {{ "selected" if car and car.contract and car.contract.value=="长期" else "" }}>长期</option>
      <option value="短期" {{ "selected" if car and car.contract and car.contract.value=="短期" else "" }}>短期</option>
    </select>
```
并在 `app/routers/cars.py` 的 create/edit 两个 POST 读取 `contract: str = Form("")`,转 `ContractType(contract) if contract else None`,通过 `csvc.create_car(..., )` / `update_car` 写入(给 `create_car`/`update_car` 增加 `contract` 形参并存到 `car.contract`)。

- [ ] **Step 6: 车页显示薪资+合同、队页显示预算**——`car_detail` 路由计算当前赛季(`ssvc.get_active_season`,无则跳过)薪资 `sal.compute_salary` 传模板;`car_detail.html` 在 MMR 卡片区加一格"薪资"。`team_detail` 路由算 `bud.compute_budget` 传模板;`team_detail.html` 头部加"预算"。(若无活动赛季,显示"—"。)

- [ ] **Step 7:** `pytest` 全量 PASS;`uvicorn` 冒烟开 `/cars/<id>`、`/teams/<id>` 看到薪资/预算。

- [ ] **Step 8: 提交** `git add -A && git commit -m "feat(market): season snapshot + show salary/budget + contract field"`

---

## 自检
- **Spec 覆盖**:合同字段(T1/T6)、车队积分新规则(T2/T3)、薪资公式含 MMR 折扣/名宿/冠军/决赛圈(T4)、预算公式含冠军单/队加成(T5)、赛季快照与展示(T6)。市场流程(释放/选秀/签约/确认/页面)属**计划B**。
- **占位扫描**:T1 Step2 的 standings 临时 `pass` 在 T3 Step4 被真实实现替换——非遗留 TODO,是按"每步可运行"的过渡;已显式标注。
- **类型一致**:`racestats.car_advancements/car_achievements/car_podium/final_ranking`、`team_points.award`、`salary.compute_salary`、`budget.compute_budget`、`market_snapshot.snapshot_season`、`standings.award_race` 在定义、调用、测试中签名一致;`advance_round` 改调 `award_race`。
- **回归**:T3 明确要求修改 test_standings / test_honors_integration 的旧分值断言为新规则。
