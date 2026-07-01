# 转会选秀重构 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把全自动的转会补位改成「按余额逐队、逐类别手动取舍 + 挖角」的半自动选秀,建议仅供参考,全程可重置。

**Architecture:** 新增两张表 `MarketDraft`(草稿状态:参照赛季、锁定队集合、当前队、已锁类别、随机种子)与 `DraftCarSnapshot`(开盘时全车 team_id/status 快照,供一键重置)。经济计算(预算/薪资/余额)留在 `app/services/market.py`;有状态的选秀流程(开盘/队列/进队/候选池/建议/锁定/确认/重置/定档)放新模块 `app/services/market_draft.py`。签约/挖角/释放即时改写 `Car` 行,与现有赛事流程一致。路由与模板重写为单页流程 + HTMX 局部刷新。

**Tech Stack:** Python 3.9(每模块首行 `from __future__ import annotations`,SQLModel 表用 `Optional[...]`)、FastAPI、SQLModel、Jinja2 + HTMX、pytest + TestClient。内存库测试见 `tests/conftest.py`。权威设计见 [docs/superpowers/specs/2026-07-02-transfer-draft-redesign-design.md](../specs/2026-07-02-transfer-draft-redesign-design.md)。

---

## 文件结构与接口(先锁定,再拆任务)

**新建**
- `app/services/market_draft.py` —— 选秀状态机 + 候选池 + 建议。对外接口:
  - `open_draft(session) -> MarketDraft` —— 建草稿 + 快照全车;若已存在草稿则复用。
  - `get_draft(session) -> Optional[MarketDraft]`
  - `reset_draft(session) -> None` —— 用快照还原所有车,清空锁定集合/当前队/已锁类别。
  - `close_draft(session) -> None` —— 删草稿与快照(定档后)。
  - `locked_team_ids(draft) -> set[int]` / `locked_categories(draft) -> set[Category]` —— 解析 csv 字段。
  - `priority_key(session, draft, team_id, ref_id) -> tuple` —— 排序键 `(-余额, -车队积分, -最高MMR, 随机)`。
  - `draft_queue(session) -> list[dict]` —— 每队 `{team, headroom, points, locked, is_current}`;未锁队按 `priority_key` 升序(键已取负,故余额高者在前)。
  - `enter_team(session, team_id) -> None` —— 校验无当前队且 team 为最高优先未锁队;设为当前队;自动解约其全部短期车。
  - `category_pool(session, team_id, category) -> list[dict]` —— 候选池 `{car, salary, affordable}`。
  - `category_recommendation(session, team_id, category) -> dict` —— `{keep:[car_id...], can_disband:bool, strengthen:[car_id...]}`。
  - `lock_category(session, team_id, category, slot_car_ids: list) -> None` —— 校验 + 应用(release/sign/poach),记该类别已锁。
  - `unlock_category(session, team_id, category) -> None` —— 释放该 (队,类别) 全部非长期现役车回自由池,清该类别锁。
  - `confirm_team(session, team_id) -> None` —— 要求 3 类别全锁;加入锁定集合;清当前队与已锁类别。
- `app/templates/_market_queue.html`、`_market_current.html` —— HTMX 局部。
- `tests/test_market_draft.py` —— 新流程测试。

**修改**
- `app/models.py` —— 加 `MarketDraft`、`DraftCarSnapshot`。
- `app/services/market.py` —— 保留 `MarketError`、`reference_season`、`season_pair`、`committed_salary`、`headroom`;**删除** `open_market`、`sign`、`release`、`recommend`、`_active_in_category`、`_free_agents`、`_partial_categories`、`_team_has_need`;新增底层原语 `assign_car`、`release_car`。
- `app/routers/market.py` —— 重写端点。
- `app/templates/market.html` —— 重写为单页选秀。
- `tests/test_market.py` —— 删旧 flow 测试(open_market/recommend/sign 自动),保留并改写「经济计算 + 品牌锁 via lock_category」测试。

**约定**
- `Category` 与其字符串:`Category.F1="F1"`、`Category.GT3="GT3"`、`Category.ROAD="公路车"`。csv 用 `category.value`。
- 「现役」= `status in ACTIVE_STATUSES`(LONG/SHORT)。
- 空槽在表单里传空字符串,服务层解析为 `None`。

---

## Task 1: 数据模型 MarketDraft / DraftCarSnapshot

**Files:**
- Modify: `app/models.py`(在文件末尾追加)
- Test: `tests/test_market_draft.py`(新建)

- [ ] **Step 1: 写失败测试**

创建 `tests/test_market_draft.py`:

```python
from __future__ import annotations

from sqlmodel import select
from app.enums import Category, TeamType, CarStatus
from app.services import seasons as ssvc, teams as tsvc, cars as csvc
from app.services import market, market_draft as md
from app.models import Car, MarketDraft, DraftCarSnapshot


def test_models_exist_and_default():
    d = MarketDraft(reference_season_id=1, tiebreak_seed=7)
    assert d.current_team_id is None
    assert d.locked_team_ids == "" and d.locked_categories == ""
    snap = DraftCarSnapshot(draft_id=1, car_id=1, orig_team_id=None,
                            orig_status=CarStatus.UNSIGNED)
    assert snap.orig_status == CarStatus.UNSIGNED
```

- [ ] **Step 2: 运行,确认失败**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py::test_models_exist_and_default -v`
Expected: FAIL `ImportError: cannot import name 'MarketDraft'`

- [ ] **Step 3: 加模型**

在 `app/models.py` 末尾追加(`Category`、`CarStatus` 已在文件顶部导入):

```python
class MarketDraft(SQLModel, table=True):
    """一次转会选秀的草稿状态(开盘到定档之间)。同一时刻至多一条。"""
    id: Optional[int] = Field(default=None, primary_key=True)
    reference_season_id: int = Field(foreign_key="season.id")
    current_team_id: Optional[int] = Field(default=None, foreign_key="team.id")
    locked_team_ids: str = ""        # 逗号分隔的已确认队 id
    locked_categories: str = ""      # 当前队里已锁定类别(Category.value,逗号分隔)
    tiebreak_seed: int = 0           # 平局随机裁决种子,开盘时定
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DraftCarSnapshot(SQLModel, table=True):
    """开盘时每辆车的原始归属/状态,供一键重置还原。"""
    id: Optional[int] = Field(default=None, primary_key=True)
    draft_id: int = Field(foreign_key="marketdraft.id")
    car_id: int = Field(foreign_key="car.id")
    orig_team_id: Optional[int] = Field(default=None, foreign_key="team.id")
    orig_status: CarStatus = CarStatus.UNSIGNED
```

- [ ] **Step 4: 运行,确认通过**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py::test_models_exist_and_default -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/models.py tests/test_market_draft.py
git commit -m "feat(market): 新增 MarketDraft/DraftCarSnapshot 数据模型"
```

---

## Task 2: market.py 底层原语 assign_car / release_car

保留经济计算,新增两个不含流程语义的底层改写函数,供 market_draft 复用。**本任务不删旧函数**(留到 Task 10,保持中途测试绿)。

**Files:**
- Modify: `app/services/market.py`
- Test: `tests/test_market_draft.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_market_draft.py`:

```python
def test_assign_and_release_primitives(session):
    ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    c = csvc.create_car(session, nickname="c", category=Category.GT3, brand="X",
                        casting="", description="", team_id=None)
    market.assign_car(session, c, t.id, CarStatus.SHORT)
    session.expire_all()
    c = session.get(Car, c.id)
    assert c.team_id == t.id and c.status == CarStatus.SHORT
    market.release_car(session, c)
    session.expire_all()
    c = session.get(Car, c.id)
    assert c.team_id is None and c.status == CarStatus.UNSIGNED
```

- [ ] **Step 2: 运行,确认失败**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py::test_assign_and_release_primitives -v`
Expected: FAIL `AttributeError: module 'app.services.market' has no attribute 'assign_car'`

- [ ] **Step 3: 加原语**

在 `app/services/market.py` 末尾追加:

```python
def assign_car(session: Session, car: Car, team_id: int, status: CarStatus) -> None:
    """底层:把 car 落到 team(现役状态),不做校验(校验在调用方)。"""
    car.team_id = team_id
    car.status = status
    session.add(car)
    session.commit()


def release_car(session: Session, car: Car) -> None:
    """底层:解约 car → 未签约、无车队。"""
    car.team_id = None
    car.status = CarStatus.UNSIGNED
    session.add(car)
    session.commit()
```

- [ ] **Step 4: 运行,确认通过**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py::test_assign_and_release_primitives -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/market.py tests/test_market_draft.py
git commit -m "feat(market): 底层 assign_car/release_car 原语"
```

---

## Task 3: 开盘 / 快照 / 重置 / 关闭

**Files:**
- Create: `app/services/market_draft.py`
- Test: `tests/test_market_draft.py`

- [ ] **Step 1: 写失败测试**

追加:

```python
def _seed_two_teams(session):
    ssvc.start_season(session, name="S1")
    ta = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="A")
    tb = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="B")
    long_a = csvc.create_car(session, nickname="A长", category=Category.GT3, brand="X",
                             casting="", description="", team_id=ta.id, signed_status=CarStatus.LONG)
    short_a = csvc.create_car(session, nickname="A短", category=Category.GT3, brand="X",
                              casting="", description="", team_id=ta.id, signed_status=CarStatus.SHORT)
    return ta, tb, long_a, short_a


def test_open_snapshots_all_and_does_not_release(session):
    ta, tb, long_a, short_a = _seed_two_teams(session)
    d = md.open_draft(session)
    session.expire_all()
    # 开盘不改动任何车
    assert session.get(Car, short_a.id).status == CarStatus.SHORT
    snaps = session.exec(select(DraftCarSnapshot).where(
        DraftCarSnapshot.draft_id == d.id)).all()
    assert len(snaps) == 2                       # 全车各一行
    assert md.get_draft(session).id == d.id


def test_reset_restores_from_snapshot(session):
    ta, tb, long_a, short_a = _seed_two_teams(session)
    md.open_draft(session)
    # 手动把短期车释放(模拟中途改动)
    market.release_car(session, session.get(Car, short_a.id))
    md.reset_draft(session)
    session.expire_all()
    c = session.get(Car, short_a.id)
    assert c.team_id == ta.id and c.status == CarStatus.SHORT
    d = md.get_draft(session)
    assert d.locked_team_ids == "" and d.current_team_id is None
```

- [ ] **Step 2: 运行,确认失败**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py -k "open_snapshots or reset_restores" -v`
Expected: FAIL(`market_draft` 无 `open_draft`)

- [ ] **Step 3: 建模块**

创建 `app/services/market_draft.py`:

```python
from __future__ import annotations

import random
from typing import Optional
from sqlmodel import Session, select
from app.models import Car, Team, MarketDraft, DraftCarSnapshot
from app.enums import Category, CarStatus, TeamType, ACTIVE_STATUSES
from app.config import MAX_CARS_PER_CATEGORY
from app.services import market, teams as tsvc, salary as sal, standings as st


class DraftError(Exception):
    pass


def get_draft(session: Session) -> Optional[MarketDraft]:
    return session.exec(select(MarketDraft).order_by(MarketDraft.id.desc())).first()


def open_draft(session: Session) -> MarketDraft:
    existing = get_draft(session)
    if existing is not None:
        return existing
    ref = market.reference_season(session)
    if ref is None:
        raise DraftError("没有可参照的赛季,无法开盘")
    draft = MarketDraft(reference_season_id=ref.id,
                        tiebreak_seed=random.randint(0, 10 ** 9))
    session.add(draft); session.commit(); session.refresh(draft)
    for c in session.exec(select(Car)).all():
        session.add(DraftCarSnapshot(draft_id=draft.id, car_id=c.id,
                    orig_team_id=c.team_id, orig_status=c.status))
    session.commit()
    return draft


def reset_draft(session: Session) -> None:
    draft = get_draft(session)
    if draft is None:
        return
    for snap in session.exec(select(DraftCarSnapshot).where(
            DraftCarSnapshot.draft_id == draft.id)).all():
        car = session.get(Car, snap.car_id)
        if car is not None:
            car.team_id = snap.orig_team_id
            car.status = snap.orig_status
            session.add(car)
    draft.current_team_id = None
    draft.locked_team_ids = ""
    draft.locked_categories = ""
    session.add(draft); session.commit()


def close_draft(session: Session) -> None:
    draft = get_draft(session)
    if draft is None:
        return
    for snap in session.exec(select(DraftCarSnapshot).where(
            DraftCarSnapshot.draft_id == draft.id)).all():
        session.delete(snap)
    session.delete(draft); session.commit()


def locked_team_ids(draft: MarketDraft) -> set:
    return {int(x) for x in draft.locked_team_ids.split(",") if x}


def locked_categories(draft: MarketDraft) -> set:
    return {Category(x) for x in draft.locked_categories.split(",") if x}
```

- [ ] **Step 4: 运行,确认通过**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py -k "open_snapshots or reset_restores" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/market_draft.py tests/test_market_draft.py
git commit -m "feat(market): 选秀开盘/快照/重置/关闭"
```

---

## Task 4: 优先级队列(余额 → 积分 → 最高MMR → 固定随机)

**Files:**
- Modify: `app/services/market_draft.py`
- Test: `tests/test_market_draft.py`

- [ ] **Step 1: 写失败测试**

追加:

```python
def test_queue_orders_by_headroom_then_points(session):
    ssvc.start_season(session, name="S1")
    # 两独立队各 1 长期 GT3;A 的车 MMR 低→薪资低→余额高→排前
    ta = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="A")
    tb = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="B")
    a = csvc.create_car(session, nickname="a", category=Category.GT3, brand="X",
                        casting="", description="", team_id=ta.id, signed_status=CarStatus.LONG)
    b = csvc.create_car(session, nickname="b", category=Category.GT3, brand="X",
                        casting="", description="", team_id=tb.id, signed_status=CarStatus.LONG)
    a.season_mmr = 1400; b.season_mmr = 1600
    session.add(a); session.add(b); session.commit()
    md.open_draft(session)
    q = md.draft_queue(session)
    assert [row["team"].id for row in q][:2] == [ta.id, tb.id]
    assert all("headroom" in row and "locked" in row for row in q)
```

- [ ] **Step 2: 运行,确认失败**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py::test_queue_orders_by_headroom_then_points -v`
Expected: FAIL(无 `draft_queue`)

- [ ] **Step 3: 实现队列**

在 `market_draft.py` 追加:

```python
def _max_active_mmr(session: Session, team_id: int) -> float:
    rows = session.exec(select(Car).where(Car.team_id == team_id,
                        Car.status.in_(ACTIVE_STATUSES))).all()
    return max((c.season_mmr for c in rows), default=float("-inf"))


def priority_key(session: Session, draft: MarketDraft, team_id: int, ref_id: int):
    """排序键:余额高→积分高→最高MMR高→固定随机。取负实现降序。"""
    hr = market.headroom(session, team_id, ref_id)
    pts = st.team_season_points(session, team_id, ref_id)
    mmr = _max_active_mmr(session, team_id)
    rnd = random.Random("%d-%d" % (draft.tiebreak_seed, team_id)).random()
    return (-hr, -pts, -mmr, rnd)


def draft_queue(session: Session) -> list:
    draft = get_draft(session)
    if draft is None:
        return []
    ref_id = draft.reference_season_id
    locked = locked_team_ids(draft)
    rows = []
    for t in session.exec(select(Team)).all():
        rows.append({
            "team": t,
            "headroom": market.headroom(session, t.id, ref_id),
            "points": st.team_season_points(session, t.id, ref_id),
            "locked": t.id in locked,
            "is_current": t.id == draft.current_team_id,
            "_key": priority_key(session, draft, t.id, ref_id),
        })
    # 已锁沉底;未锁按 priority_key 升序(键已取负)
    rows.sort(key=lambda r: (r["locked"], r["_key"]))
    for r in rows:
        r.pop("_key")
    return rows
```

- [ ] **Step 4: 运行,确认通过**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py::test_queue_orders_by_headroom_then_points -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/market_draft.py tests/test_market_draft.py
git commit -m "feat(market): 选秀优先级队列(余额/积分/MMR/固定随机)"
```

---

## Task 5: 进入当前队(自动解约自家短期)

**Files:**
- Modify: `app/services/market_draft.py`
- Test: `tests/test_market_draft.py`

- [ ] **Step 1: 写失败测试**

追加:

```python
def test_enter_team_releases_own_shorts_only(session):
    ssvc.start_season(session, name="S1")
    ta = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="A")
    tb = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="B")
    a_long = csvc.create_car(session, nickname="A长", category=Category.GT3, brand="X",
                             casting="", description="", team_id=ta.id, signed_status=CarStatus.LONG)
    a_short = csvc.create_car(session, nickname="A短", category=Category.F1, brand="X",
                              casting="", description="", team_id=ta.id, signed_status=CarStatus.SHORT)
    b_short = csvc.create_car(session, nickname="B短", category=Category.GT3, brand="X",
                              casting="", description="", team_id=tb.id, signed_status=CarStatus.SHORT)
    md.open_draft(session)
    top = md.draft_queue(session)[0]["team"].id     # 余额最高者
    md.enter_team(session, top)
    session.expire_all()
    d = md.get_draft(session)
    assert d.current_team_id == top
    # 当前队自家短期被解约;长期保留;他队短期不动
    if top == ta.id:
        assert session.get(Car, a_short.id).status == CarStatus.UNSIGNED
        assert session.get(Car, a_long.id).status == CarStatus.LONG
        assert session.get(Car, b_short.id).status == CarStatus.SHORT


def test_enter_rejects_when_not_top_or_busy(session):
    import pytest
    ssvc.start_season(session, name="S1")
    ta = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="A")
    tb = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="B")
    csvc.create_car(session, nickname="a", category=Category.GT3, brand="X", casting="",
                    description="", team_id=ta.id, signed_status=CarStatus.LONG)
    md.open_draft(session)
    q = md.draft_queue(session)
    top, other = q[0]["team"].id, q[1]["team"].id
    md.enter_team(session, top)
    with pytest.raises(md.DraftError):
        md.enter_team(session, other)               # 已有当前队
```

- [ ] **Step 2: 运行,确认失败**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py -k "enter_team or enter_rejects" -v`
Expected: FAIL(无 `enter_team`)

- [ ] **Step 3: 实现 enter_team**

追加:

```python
def _highest_unlocked(session: Session, draft: MarketDraft) -> Optional[int]:
    for row in draft_queue(session):
        if not row["locked"]:
            return row["team"].id
    return None


def enter_team(session: Session, team_id: int) -> None:
    draft = get_draft(session)
    if draft is None:
        raise DraftError("尚未开盘")
    if draft.current_team_id is not None:
        raise DraftError("已有正在处理的车队,请先确认或重置")
    if team_id in locked_team_ids(draft):
        raise DraftError("该车队已确认")
    if team_id != _highest_unlocked(session, draft):
        raise DraftError("必须先处理当前余额最高的车队")
    # 自动解约自家短期
    for c in session.exec(select(Car).where(Car.team_id == team_id,
                          Car.status == CarStatus.SHORT)).all():
        market.release_car(session, c)
    draft.current_team_id = team_id
    draft.locked_categories = ""
    session.add(draft); session.commit()
```

- [ ] **Step 4: 运行,确认通过**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py -k "enter_team or enter_rejects" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/market_draft.py tests/test_market_draft.py
git commit -m "feat(market): 进入当前队并自动解约自家短期"
```

---

## Task 6: 候选池 + 建议

**Files:**
- Modify: `app/services/market_draft.py`
- Test: `tests/test_market_draft.py`

- [ ] **Step 1: 写失败测试**

追加:

```python
def test_pool_includes_free_and_other_short_excludes_long(session):
    ssvc.start_season(session, name="S1")
    ta = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="A")
    tb = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="B")
    free = csvc.create_car(session, nickname="自由", category=Category.GT3, brand="X",
                           casting="", description="", team_id=None)
    b_short = csvc.create_car(session, nickname="B短", category=Category.GT3, brand="X",
                              casting="", description="", team_id=tb.id, signed_status=CarStatus.SHORT)
    b_long = csvc.create_car(session, nickname="B长", category=Category.GT3, brand="X",
                             casting="", description="", team_id=tb.id, signed_status=CarStatus.LONG)
    md.open_draft(session)
    md.enter_team(session, md.draft_queue(session)[0]["team"].id)
    ids = {row["car"].id for row in md.category_pool(session, ta.id, Category.GT3)}
    assert free.id in ids and b_short.id in ids       # 自由 + 他队短期(挖角)
    assert b_long.id not in ids                        # 长期不入池


def test_pool_factory_brand_lock(session):
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    ok = csvc.create_car(session, nickname="无牌", category=Category.GT3, brand="无",
                         casting="", description="", team_id=None)
    bad = csvc.create_car(session, nickname="保时捷车", category=Category.GT3, brand="保时捷",
                          casting="", description="", team_id=None)
    md.open_draft(session)
    md.enter_team(session, tf.id)
    ids = {row["car"].id for row in md.category_pool(session, tf.id, Category.GT3)}
    assert ok.id in ids and bad.id not in ids


def test_recommendation_shapes(session):
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    lg = csvc.create_car(session, nickname="法长", category=Category.GT3, brand="法拉利",
                         casting="", description="", team_id=tf.id, signed_status=CarStatus.LONG)
    free = csvc.create_car(session, nickname="法自由", category=Category.GT3, brand="法拉利",
                           casting="", description="", team_id=None)
    md.open_draft(session)
    md.enter_team(session, tf.id)
    rec = md.category_recommendation(session, tf.id, Category.GT3)
    assert lg.id in rec["keep"]                 # 长期车必在保持里
    assert rec["can_disband"] is False          # 有长期车不能解散
    assert free.id in rec["strengthen"]         # 补强会带上长期车 + 自由车
```

- [ ] **Step 2: 运行,确认失败**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py -k "pool_ or recommendation_shapes" -v`
Expected: FAIL(无 `category_pool`)

- [ ] **Step 3: 实现候选池 + 建议**

追加:

```python
def _brand_ok(team: Team, car: Car) -> bool:
    return not (team.type == TeamType.FACTORY
                and not tsvc.is_brandless(car.brand)
                and car.brand != team.brand)


def _long_cars(session: Session, team_id: int, category: Category):
    return session.exec(select(Car).where(Car.team_id == team_id,
        Car.category == category, Car.status == CarStatus.LONG)).all()


def category_pool(session: Session, team_id: int, category: Category) -> list:
    """某 (队,类别) 一个自由槽的候选池:自由身 + 未确认他队短期 + 本队该类别现有现役;
    去掉长期车、已确认队的车、退役车;按品牌过滤;标注是否买得起。"""
    draft = get_draft(session)
    ref_id = draft.reference_season_id
    locked = locked_team_ids(draft)
    team = session.get(Team, team_id)
    hr = market.headroom(session, team_id, ref_id)
    out, seen = [], set()
    for c in session.exec(select(Car).where(Car.category == category)).all():
        if c.id in seen or c.status == CarStatus.RETIRED:
            continue
        if c.status == CarStatus.LONG:
            continue                                  # 长期不可流动
        own = (c.team_id == team_id)
        free = (c.team_id is None)
        other_short = (c.team_id is not None and c.team_id != team_id
                       and c.team_id not in locked and c.status == CarStatus.SHORT)
        if not (own or free or other_short):
            continue
        if not _brand_ok(team, c):
            continue
        price = sal.compute_salary(session, c, ref_id)
        out.append({"car": c, "salary": price, "affordable": price <= hr})
        seen.add(c.id)
    out.sort(key=lambda r: sal._season_mmr(session, r["car"], ref_id), reverse=True)
    return out


def category_recommendation(session: Session, team_id: int, category: Category) -> dict:
    draft = get_draft(session)
    ref_id = draft.reference_season_id
    longs = _long_cars(session, team_id, category)
    long_ids = [c.id for c in longs]
    # 保持不变:进队前该类别的原阵容(长期 + 快照里属于本队该类别的短期)
    keep = list(long_ids)
    for snap in session.exec(select(DraftCarSnapshot).where(
            DraftCarSnapshot.draft_id == draft.id)).all():
        car = session.get(Car, snap.car_id)
        if (snap.orig_team_id == team_id and car is not None
                and car.category == category and snap.orig_status == CarStatus.SHORT):
            keep.append(car.id)
    keep = keep[:MAX_CARS_PER_CATEGORY]
    # 补强:长期车钉死,其余槽从候选池取买得起的最高 MMR
    strengthen = list(long_ids)
    hr = market.headroom(session, team_id, ref_id)
    for row in category_pool(session, team_id, category):
        if len(strengthen) >= MAX_CARS_PER_CATEGORY:
            break
        if row["car"].id in strengthen:
            continue
        if row["salary"] <= hr:
            strengthen.append(row["car"].id)
            hr -= row["salary"]
    return {"keep": keep, "can_disband": len(longs) == 0, "strengthen": strengthen}
```

- [ ] **Step 4: 运行,确认通过**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py -k "pool_ or recommendation_shapes" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/market_draft.py tests/test_market_draft.py
git commit -m "feat(market): 候选池(含挖角/品牌锁)与三种建议"
```

---

## Task 7: 锁定类别(校验 + 应用)

**Files:**
- Modify: `app/services/market_draft.py`
- Test: `tests/test_market_draft.py`

校验顺序见 spec §4:①顺序(含长期车类别优先)②品牌 ③长期钉死不可移除 ④数量(含长期补满2,逃生阀允许1;无长期0或2)⑤预算(唯一例外=含长期车类别长期本身超支)⑥来源合法。

- [ ] **Step 1: 写失败测试**

追加:

```python
def _enter_top(session):
    md.open_draft(session)
    tid = md.draft_queue(session)[0]["team"].id
    md.enter_team(session, tid)
    return tid


def test_lock_fills_long_category_to_two(session):
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    lg = csvc.create_car(session, nickname="法长", category=Category.GT3, brand="法拉利",
                         casting="", description="", team_id=tf.id, signed_status=CarStatus.LONG)
    free = csvc.create_car(session, nickname="法自由", category=Category.GT3, brand="法拉利",
                           casting="", description="", team_id=None)
    _enter_top(session)
    md.lock_category(session, tf.id, Category.GT3, [lg.id, free.id])
    session.expire_all()
    assert session.get(Car, free.id).team_id == tf.id
    assert session.get(Car, free.id).status == CarStatus.SHORT     # 签下默认短期
    assert Category.GT3 in md.locked_categories(md.get_draft(session))


def test_lock_long_category_may_stop_at_one_when_no_car(session):
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    lg = csvc.create_car(session, nickname="法长", category=Category.GT3, brand="法拉利",
                         casting="", description="", team_id=tf.id, signed_status=CarStatus.LONG)
    _enter_top(session)     # 池中无第二辆法拉利 GT3
    md.lock_category(session, tf.id, Category.GT3, [lg.id, None])  # 逃生阀:允许 1
    assert Category.GT3 in md.locked_categories(md.get_draft(session))


def test_lock_rejects_one_active_when_car_available(session):
    import pytest
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    lg = csvc.create_car(session, nickname="法长", category=Category.GT3, brand="法拉利",
                         casting="", description="", team_id=tf.id, signed_status=CarStatus.LONG)
    csvc.create_car(session, nickname="法自由", category=Category.GT3, brand="法拉利",
                    casting="", description="", team_id=None)
    _enter_top(session)
    with pytest.raises(md.DraftError):
        md.lock_category(session, tf.id, Category.GT3, [lg.id, None])  # 有车却停在1 → 拒


def test_lock_order_long_first(session):
    import pytest
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    # GT3 有长期车;F1 无长期车
    csvc.create_car(session, nickname="法长", category=Category.GT3, brand="法拉利",
                    casting="", description="", team_id=tf.id, signed_status=CarStatus.LONG)
    _enter_top(session)
    with pytest.raises(md.DraftError):
        md.lock_category(session, tf.id, Category.F1, [None, None])   # GT3(含长期)未锁完
```

- [ ] **Step 2: 运行,确认失败**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py -k "lock_" -v`
Expected: FAIL(无 `lock_category`)

- [ ] **Step 3: 实现 lock_category**

追加:

```python
def _has_long(session: Session, team_id: int, category: Category) -> bool:
    return len(_long_cars(session, team_id, category)) > 0


def _unlocked_long_categories(session: Session, team_id: int, draft: MarketDraft) -> set:
    done = locked_categories(draft)
    return {cat for cat in Category
            if _has_long(session, team_id, cat) and cat not in done}


def lock_category(session: Session, team_id: int, category: Category,
                  slot_car_ids: list) -> None:
    draft = get_draft(session)
    if draft is None or draft.current_team_id != team_id:
        raise DraftError("该车队不是当前处理的车队")
    if category in locked_categories(draft):
        raise DraftError("该类别已锁定,请先解锁")
    team = session.get(Team, team_id)
    ref_id = draft.reference_season_id
    chosen_ids = [cid for cid in slot_car_ids if cid]

    # ① 顺序:含长期车类别必须先锁
    if not _has_long(session, team_id, category):
        pending = _unlocked_long_categories(session, team_id, draft)
        if pending:
            raise DraftError("请先锁定含长期车的类别:"
                             + "、".join(c.value for c in pending))

    # 目标车与当前该类别现役对比
    long_ids = {c.id for c in _long_cars(session, team_id, category)}
    if not long_ids.issubset(set(chosen_ids)):
        raise DraftError("长期车不可移除,必须保留在阵容中")
    if len(chosen_ids) > MAX_CARS_PER_CATEGORY:
        raise DraftError("每类别最多 2 个现役")

    pool = {row["car"].id: row for row in category_pool(session, team_id, category)}
    # ② 品牌 + ⑥ 来源合法:非长期的选中车必须来自候选池
    for cid in chosen_ids:
        if cid in long_ids:
            continue
        if cid not in pool:
            raise DraftError("所选车不在候选池中(品牌/归属/退役不合法)")

    # ④ 数量 + 逃生阀
    has_long = bool(long_ids)
    if len(chosen_ids) == MAX_CARS_PER_CATEGORY:
        pass
    elif len(chosen_ids) <= 1:
        # 是否还有「合法+买得起」的可加车?有则不允许停在 <2
        addable = [r for cid2, r in pool.items()
                   if cid2 not in chosen_ids and r["affordable"]]
        if addable:
            raise DraftError("该类别可补强,不能停在不足 2 个现役")
        if not has_long and len(chosen_ids) == 1:
            raise DraftError("无长期车的类别必须是 0 或 2 个现役")

    # 计算这批选择将产生的薪资与预算校验(⑤)
    # 先算「不含本类别」的其余现役薪资
    other_salary = 0
    for c in session.exec(select(Car).where(Car.team_id == team_id,
                          Car.status.in_(ACTIVE_STATUSES))).all():
        if c.category != category:
            other_salary += sal.compute_salary(session, c, ref_id)
    chosen_salary = sum(sal.compute_salary(session, session.get(Car, cid), ref_id)
                        for cid in chosen_ids)
    budget = market.bud.compute_budget(session, team, ref_id)
    long_only_salary = sum(sal.compute_salary(session, session.get(Car, cid), ref_id)
                           for cid in long_ids)
    over = other_salary + chosen_salary > budget
    long_only_over = other_salary + long_only_salary > budget
    if over and not (has_long and chosen_salary == long_only_salary and long_only_over):
        raise DraftError("超出预算")

    # ---- 应用:先把本类别现有非长期现役全部释放,再签入选中的非长期车 ----
    for c in session.exec(select(Car).where(Car.team_id == team_id,
                          Car.category == category,
                          Car.status.in_(ACTIVE_STATUSES))).all():
        if c.id not in long_ids:
            market.release_car(session, c)
    for cid in chosen_ids:
        if cid in long_ids:
            continue
        market.assign_car(session, session.get(Car, cid), team_id, CarStatus.SHORT)

    cats = locked_categories(draft)
    cats.add(category)
    draft.locked_categories = ",".join(c.value for c in cats)
    session.add(draft); session.commit()
```

> 注:`market.bud` 需在 `market.py` 顶部已 `from app.services import ... budget as bud`(现有)。若未暴露,改为在 `market_draft.py` 顶部 `from app.services import budget as bud` 并用 `bud.compute_budget`。

- [ ] **Step 4: 运行,确认通过**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py -k "lock_" -v`
Expected: PASS

若 `market.bud` 报错,改用直接导入 `bud`(见上注),再跑。

- [ ] **Step 5: 提交**

```bash
git add app/services/market_draft.py tests/test_market_draft.py
git commit -m "feat(market): 锁定类别(顺序/品牌/长期钉死/数量逃生阀/预算校验)"
```

---

## Task 8: 解锁类别 + 确认车队

**Files:**
- Modify: `app/services/market_draft.py`
- Test: `tests/test_market_draft.py`

- [ ] **Step 1: 写失败测试**

追加:

```python
def test_unlock_reverts_to_baseline(session):
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    lg = csvc.create_car(session, nickname="法长", category=Category.GT3, brand="法拉利",
                         casting="", description="", team_id=tf.id, signed_status=CarStatus.LONG)
    free = csvc.create_car(session, nickname="法自由", category=Category.GT3, brand="法拉利",
                           casting="", description="", team_id=None)
    _enter_top(session)
    md.lock_category(session, tf.id, Category.GT3, [lg.id, free.id])
    md.unlock_category(session, tf.id, Category.GT3)
    session.expire_all()
    assert session.get(Car, free.id).team_id is None            # 补强车退回自由
    assert session.get(Car, lg.id).status == CarStatus.LONG     # 长期车仍在
    assert Category.GT3 not in md.locked_categories(md.get_draft(session))


def test_confirm_requires_all_three_locked(session):
    import pytest
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    _enter_top(session)
    with pytest.raises(md.DraftError):
        md.confirm_team(session, tf.id)                         # 一个都没锁
    for cat in Category:
        md.lock_category(session, tf.id, cat, [None, None])
    md.confirm_team(session, tf.id)
    session.expire_all()
    d = md.get_draft(session)
    assert tf.id in md.locked_team_ids(d) and d.current_team_id is None
```

- [ ] **Step 2: 运行,确认失败**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py -k "unlock_reverts or confirm_requires" -v`
Expected: FAIL(无 `unlock_category`)

- [ ] **Step 3: 实现 unlock + confirm**

追加:

```python
def unlock_category(session: Session, team_id: int, category: Category) -> None:
    draft = get_draft(session)
    if draft is None or draft.current_team_id != team_id:
        raise DraftError("该车队不是当前处理的车队")
    # 释放该类别全部非长期现役回自由池(回到进队后基线:仅长期车)
    for c in session.exec(select(Car).where(Car.team_id == team_id,
                          Car.category == category,
                          Car.status.in_(ACTIVE_STATUSES))).all():
        if c.status != CarStatus.LONG:
            market.release_car(session, c)
    cats = locked_categories(draft)
    cats.discard(category)
    draft.locked_categories = ",".join(c.value for c in cats)
    session.add(draft); session.commit()


def confirm_team(session: Session, team_id: int) -> None:
    draft = get_draft(session)
    if draft is None or draft.current_team_id != team_id:
        raise DraftError("该车队不是当前处理的车队")
    if locked_categories(draft) != set(Category):
        raise DraftError("三个类别都锁定后才能确认")
    locked = locked_team_ids(draft)
    locked.add(team_id)
    draft.locked_team_ids = ",".join(str(i) for i in sorted(locked))
    draft.current_team_id = None
    draft.locked_categories = ""
    session.add(draft); session.commit()
```

- [ ] **Step 4: 运行,确认通过**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py -k "unlock_reverts or confirm_requires" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/market_draft.py tests/test_market_draft.py
git commit -m "feat(market): 解锁类别与确认车队"
```

---

## Task 9: 全流程收敛测试(防死锁)

不写新实现,只加一个「跑完全部车队」的集成测试,验证队列必然收敛、逃生阀有效。

**Files:**
- Test: `tests/test_market_draft.py`

- [ ] **Step 1: 写测试**

追加:

```python
def test_full_draft_converges(session):
    ssvc.start_season(session, name="S1")
    tids = []
    for i in range(4):
        if i < 2:
            t = tsvc.create_team(session, type=TeamType.FACTORY, brand=["法拉利", "红牛"][i], name=None)
        else:
            t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name=f"独立{i}")
        tids.append(t.id)
        for cat in Category:
            for k in range(2):
                brand = session.get(__import__('app.models', fromlist=['Team']).Team, t.id).brand or "无"
                csvc.create_car(session, nickname=f"T{i}-{cat.value}-{k}", category=cat,
                                brand=brand, casting="", description="", team_id=t.id,
                                signed_status=[CarStatus.LONG, CarStatus.SHORT][k])
    md.open_draft(session)
    guard = 0
    while True:
        guard += 1
        assert guard < 50, "队列未收敛"
        top = md._highest_unlocked(session, md.get_draft(session))
        if top is None:
            break
        md.enter_team(session, top)
        for cat in sorted(Category, key=lambda c: not md._has_long(session, top, cat)):
            rec = md.category_recommendation(session, top, cat)
            md.lock_category(session, top, cat, (rec["strengthen"] + [None, None])[:2])
        md.confirm_team(session, top)
    session.expire_all()
    # 全部车队已确认
    assert md.locked_team_ids(md.get_draft(session)) == set(tids)
```

- [ ] **Step 2: 运行,确认通过**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py::test_full_draft_converges -v`
Expected: PASS(若失败,按报错回到相关任务修正逃生阀/顺序逻辑)

- [ ] **Step 3: 提交**

```bash
git add tests/test_market_draft.py
git commit -m "test(market): 全流程收敛/防死锁集成测试"
```

---

## Task 10: 路由重写

**Files:**
- Modify: `app/routers/market.py`(整体重写)
- Test: `tests/test_market_draft.py`

- [ ] **Step 1: 写失败测试(路由)**

追加:

```python
from fastapi.testclient import TestClient
from app.main import app

_client = TestClient(app)


def test_routes_open_enter_lock_confirm(engine, session):
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    csvc.create_car(session, nickname="法长", category=Category.GT3, brand="法拉利",
                    casting="", description="", team_id=tf.id, signed_status=CarStatus.LONG)
    assert _client.post("/market/open", follow_redirects=False).status_code in (302, 303)
    assert _client.get("/market").status_code == 200
    assert _client.post("/market/enter", data={"team_id": tf.id},
                        follow_redirects=False).status_code in (302, 303)
    for cat in ["GT3", "F1", "公路车"]:
        r = _client.post("/market/lock", data={"team_id": tf.id, "category": cat,
                         "slot1": "", "slot2": ""}, follow_redirects=False)
        assert r.status_code in (302, 303)
    assert _client.post("/market/confirm", data={"team_id": tf.id},
                        follow_redirects=False).status_code in (302, 303)
    assert _client.post("/market/reset", follow_redirects=False).status_code in (302, 303)
```

> 注:锁定顺序必须先 GT3(含长期车)再 F1/公路车,测试已如此排列。

- [ ] **Step 2: 运行,确认失败**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py::test_routes_open_enter_lock_confirm -v`
Expected: FAIL(端点不存在/404)

- [ ] **Step 3: 重写路由**

把 `app/routers/market.py` 整体替换为:

```python
from __future__ import annotations

from urllib.parse import quote
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session
from app.db import get_session
from app.models import Team
from app.enums import Category
from app.services import market, market_draft as md, budget as bud
from app.routers.pages import templates

router = APIRouter()


def _redirect(msg: str = ""):
    url = "/market" + (f"?err={quote(msg)}" if msg else "")
    return RedirectResponse(url, status_code=303)


@router.get("/market", response_class=HTMLResponse)
def market_page(request: Request, err: str = "", session: Session = Depends(get_session)):
    ref = market.reference_season(session)
    draft = md.get_draft(session)
    queue = md.draft_queue(session) if draft else []
    current = None
    if draft and draft.current_team_id:
        tid = draft.current_team_id
        team = session.get(Team, tid)
        cats = []
        locked = md.locked_categories(draft)
        for cat in Category:
            cats.append({
                "category": cat,
                "locked": cat in locked,
                "pool": md.category_pool(session, tid, cat),
                "rec": md.category_recommendation(session, tid, cat),
                "has_long": md._has_long(session, tid, cat),
            })
        current = {"team": team, "cats": cats,
                   "headroom": market.headroom(session, tid, draft.reference_season_id),
                   "budget": bud.compute_budget(session, team, draft.reference_season_id)}
    return templates.TemplateResponse(request, "market.html", {
        "request": request, "ref": ref, "draft": draft,
        "queue": queue, "current": current, "err": err})


@router.post("/market/open")
def market_open(session: Session = Depends(get_session)):
    try:
        md.open_draft(session)
        return _redirect()
    except md.DraftError as e:
        return _redirect(str(e))


@router.post("/market/enter")
def market_enter(team_id: int = Form(...), session: Session = Depends(get_session)):
    try:
        md.enter_team(session, team_id); return _redirect()
    except md.DraftError as e:
        return _redirect(str(e))


@router.post("/market/lock")
def market_lock(team_id: int = Form(...), category: str = Form(...),
                slot1: str = Form(""), slot2: str = Form(""),
                session: Session = Depends(get_session)):
    slots = [int(slot1) if slot1 else None, int(slot2) if slot2 else None]
    try:
        md.lock_category(session, team_id, Category(category), slots); return _redirect()
    except md.DraftError as e:
        return _redirect(str(e))


@router.post("/market/unlock")
def market_unlock(team_id: int = Form(...), category: str = Form(...),
                  session: Session = Depends(get_session)):
    try:
        md.unlock_category(session, team_id, Category(category)); return _redirect()
    except md.DraftError as e:
        return _redirect(str(e))


@router.post("/market/confirm")
def market_confirm(team_id: int = Form(...), session: Session = Depends(get_session)):
    try:
        md.confirm_team(session, team_id); return _redirect()
    except md.DraftError as e:
        return _redirect(str(e))


@router.post("/market/reset")
def market_reset(session: Session = Depends(get_session)):
    md.reset_draft(session); return _redirect()


@router.post("/market/finalize")
def market_finalize(session: Session = Depends(get_session)):
    md.close_draft(session)
    return RedirectResponse("/seasons", status_code=303)
```

- [ ] **Step 4: 运行,确认通过**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py::test_routes_open_enter_lock_confirm -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/routers/market.py tests/test_market_draft.py
git commit -m "feat(market): 重写转会路由为选秀流程端点"
```

---

## Task 11: 页面重写(队列 + 当前队三面板)

**Files:**
- Modify: `app/templates/market.html`(整体重写)
- Test: 手动冒烟(下方命令)

- [ ] **Step 1: 重写模板**

把 `app/templates/market.html` 整体替换为:

```html
<!-- app/templates/market.html -->
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h2>转会市场</h2>
  {% if err %}<p class="error">{{ err }}</p>{% endif %}
  {% if not ref %}<p class="error">还没有已结束赛季,无法转会。</p>
  {% elif not draft %}
    <p><small>参照赛季:{{ ref.name }}</small></p>
    <form method="post" action="/market/open" style="display:inline">
      <button class="btn">开盘(建立选秀)</button></form>
  {% else %}
    <p><small>参照赛季:{{ ref.name }}</small></p>
    <form method="post" action="/market/reset" style="display:inline"
          onsubmit="return confirm('重置将还原本次转会的所有改动,确定?')">
      <button class="btn">一键重置</button></form>
    <form method="post" action="/market/finalize" style="display:inline"
          onsubmit="return confirm('结束转会并去开启下一季?')">
      <button class="btn">结束转会 → 开启下一季</button></form>
  {% endif %}
</div>

{% if draft %}
<div class="card">
  <h3>选秀队列(按余额优先)</h3>
  {% for row in queue %}
  <div class="row" style="{{ 'opacity:.5' if row.locked else '' }}">
    <span style="flex:1">
      {% if row.is_current %}▶ {% elif row.locked %}✓ {% endif %}
      <strong>{{ row.team.name }}</strong>
      <small>余额 {{ row.headroom }} · 积分 {{ row.points }}</small>
    </span>
    {% if not row.locked and not row.is_current and not current %}
    <form method="post" action="/market/enter" style="margin:0">
      <input type="hidden" name="team_id" value="{{ row.team.id }}">
      <button class="btn">处理该队</button></form>
    {% endif %}
  </div>
  {% endfor %}
</div>
{% endif %}

{% if current %}
<div class="card">
  <h3>正在处理:{{ current.team.name }}
    <small>预算 {{ current.budget }} · 余额 {{ current.headroom }}</small></h3>
  <p><small>含长期车的类别须先锁定;无长期车类别 0 或 2 个现役。</small></p>
  {% for cv in current.cats %}
  <div class="card" style="margin:8px 0">
    <div style="display:flex;justify-content:space-between">
      <strong>{{ cv.category.value }}{% if cv.has_long %}(含长期车){% endif %}</strong>
      {% if cv.locked %}
      <form method="post" action="/market/unlock" style="margin:0">
        <input type="hidden" name="team_id" value="{{ current.team.id }}">
        <input type="hidden" name="category" value="{{ cv.category.value }}">
        <button class="btn">✓ 已锁定 · 解锁重选</button></form>
      {% endif %}
    </div>
    {% if not cv.locked %}
    <form method="post" action="/market/lock">
      <input type="hidden" name="team_id" value="{{ current.team.id }}">
      <input type="hidden" name="category" value="{{ cv.category.value }}">
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        {% for slot in ['slot1', 'slot2'] %}
        <select name="{{ slot }}" style="width:auto">
          <option value="">（空）</option>
          {% for p in cv.pool %}
          <option value="{{ p.car.id }}" {{ '' if p.affordable else 'disabled' }}>
            {{ p.car.nickname }} · 薪 {{ p.salary }}{{ '' if p.affordable else '(超预算)' }}
          </option>
          {% endfor %}
        </select>
        {% endfor %}
        <button class="btn" type="submit">锁定该类别</button>
      </div>
      <p><small>建议:补强 = {{ cv.rec.strengthen }};可解散 = {{ cv.rec.can_disband }}</small></p>
    </form>
    {% endif %}
  </div>
  {% endfor %}
  <form method="post" action="/market/confirm">
    <input type="hidden" name="team_id" value="{{ current.team.id }}">
    <button class="btn" type="submit">确认该车队(三类别全锁后生效)</button></form>
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 2: 冒烟测试**

Run: `./.venv/bin/python -m pytest tests/test_market_draft.py -v`
Expected: 全部 PASS(含路由测试渲染该模板不报错)

- [ ] **Step 3: 起服务人工核对(可选)**

Run: `./.venv/bin/python -m uvicorn app.main:app --port 8099 &` 然后浏览 `/market`,确认开盘→处理队→选车锁定→确认→重置均可用;完毕 `kill %1`。

- [ ] **Step 4: 提交**

```bash
git add app/templates/market.html
git commit -m "feat(market): 转会页重写为队列+当前队三面板选秀"
```

---

## Task 12: 清理旧接口 + 改写旧测试 + 全绿

删除 `market.py` 里被取代的旧流程函数,改写 `tests/test_market.py`(去掉 open_market/recommend/sign 自动流程测试,保留经济计算与品牌锁语义——品牌锁改由 `market_draft` 覆盖,故这里只留 budget/salary/headroom 相关)。

**Files:**
- Modify: `app/services/market.py`(删函数)
- Modify: `tests/test_market.py`(重写)

- [ ] **Step 1: 删除旧函数**

从 `app/services/market.py` 删除:`open_market`、`_active_in_category`、`sign`、`release`、`_free_agents`、`_partial_categories`、`_team_has_need`、`recommend`。保留:`MarketError`、`reference_season`、`season_pair`、`committed_salary`、`headroom`、`assign_car`、`release_car`。同时删除因此不再用到的 import(`MAX_CARS_PER_CATEGORY`、`TeamType` 若未被其余保留函数使用)。

- [ ] **Step 2: 重写 tests/test_market.py**

整体替换为(仅保留仍有效的经济计算测试):

```python
from __future__ import annotations

from app.enums import Category, TeamType, CarStatus
from app.services import seasons as ssvc, teams as tsvc, cars as csvc
from app.services import market, salary as sal, budget as bud


def _seed(session):
    s = ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    long_car = csvc.create_car(session, nickname="老将", category=Category.GT3, brand="B",
                               casting="", description="", team_id=t.id,
                               signed_status=CarStatus.LONG)
    short_car = csvc.create_car(session, nickname="临时", category=Category.GT3, brand="B",
                                casting="", description="", team_id=t.id,
                                signed_status=CarStatus.SHORT)
    return s, t, long_car, short_car


def test_reference_season_prefers_finished(session):
    s, t, _, _ = _seed(session)
    assert market.reference_season(session).id == s.id
    ssvc.end_season(session, s.id)
    assert market.reference_season(session).id == s.id


def test_committed_salary_and_headroom(session):
    s, t, long_car, short_car = _seed(session)
    ssvc.end_season(session, s.id)
    ref = market.reference_season(session)
    committed = market.committed_salary(session, t.id, ref.id)
    expected = (sal.compute_salary(session, long_car, ref.id)
                + sal.compute_salary(session, short_car, ref.id))
    assert committed == expected
    assert market.headroom(session, t.id, ref.id) == \
        bud.compute_budget(session, t, ref.id) - committed


def test_committed_salary_excludes_retired(session):
    from app.services import cars as c2
    s, t, long_car, short_car = _seed(session)
    c2.change_status(session, short_car.id, CarStatus.RETIRED)
    ssvc.end_season(session, s.id)
    ref = market.reference_season(session)
    assert market.committed_salary(session, t.id, ref.id) == \
        sal.compute_salary(session, session.get(type(long_car), long_car.id), ref.id)
```

> 若 `cars.change_status` 签名不同,按实际改;目的是验证退役不计薪。可先 `grep -n "def change_status" app/services/cars.py` 确认。

- [ ] **Step 3: 运行全套**

Run: `./.venv/bin/python -m pytest -q 2>&1 | grep -iE "passed|failed|error"`
Expected: 全部 PASS(约 193 + 新增数条)。若 `test_market.py` 里 `change_status` 报错,按注释调整。

- [ ] **Step 4: 冒烟主要页面**

Run:
```bash
./.venv/bin/python -m pytest tests/test_market_draft.py tests/test_market.py -q 2>&1 | grep -iE "passed|failed"
```
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/market.py tests/test_market.py
git commit -m "refactor(market): 删除旧全自动流程,收敛为选秀接口"
```

---

## Task 13: 同步文档与 sim,守护数据库

**Files:**
- Modify: `CLAUDE.md`(转会段落)、scratchpad `sim.py`(可选)

- [ ] **Step 1: 更新 CLAUDE.md「转会市场/经济」段**

把「转会为半自动选秀…释放短期→按余额最高的队先签满→用户增删改→定档」一句改为反映新流程:「不再一刀切释放;按『维持阵容』余额排序逐队处理;进当前队自动解约自家短期;含长期车类别须先锁;候选池含未确认队短期(挖角);建议仅供参考;逃生阀防死锁;两长期类别争预算由玩家取舍。详见 2026-07-02 spec。」

- [ ] **Step 2: 确认真实库未被 schema 迁移污染**

Run: `git status --short data/hotwheel.db`
若显示已修改:`git checkout -- data/hotwheel.db`(铁律:绝不提交 schema 迁移后的库)。

- [ ] **Step 3: 全套回归**

Run: `./.venv/bin/python -m pytest -q 2>&1 | grep -iE "passed|failed|error"`
Expected: 全部 PASS

- [ ] **Step 4: 提交并推送**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md 转会段同步为选秀重构后的流程"
git push
```

---

## 自查(计划对照 spec)

- §3.1 优先级 + 平局(积分/最高MMR/固定随机)→ Task 4。
- §3.2 进队自动解约自家短期 → Task 5。
- §3.3 含长期车类别先锁 → Task 7 校验①。
- §4 锁定六项校验 + 逃生阀 → Task 7;防死锁收敛 → Task 9。
- §5 候选池(挖角/品牌/排除长期退役已确认)→ Task 6。
- §6 三种建议 → Task 6。
- §7 数据模型 `MarketDraft`/`DraftCarSnapshot` → Task 1。
- §8 服务与端点(open/queue/enter/pool/rec/lock/unlock/confirm/reset/finalize)→ Task 3–8、10;删旧 → Task 12。
- §9 测试要点 → 分散在各 Task 测试 + Task 9 集成。
- §10 严格取最高、无长期只 0/2、退役不入市 → Task 5/7 校验。
