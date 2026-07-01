# 统计/诊断(赛道公平性 + 健康自检)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增两页只读报告——`/lanes`(赛道公平性:按车道平均名次/脱轨率/拿第一,可按赛季/类别筛选)与 `/health`(健康自检:5 项铁律检查 + 概览计数,链到现场),外加 `/insights` hub 与导航入口。

**Architecture:** 全部逻辑放一个只读聚合服务 `app/services/insights.py`(纯查询,无 `add/commit`);一个路由 `app/routers/insights.py`(3 个 GET);3 个模板 + 顶栏加一个「统计」链接。数据来自现有 `HeatResult`(lane/rank/dnf)经 `Heat→Group→RaceRound→Race` 四跳 join 到 `Race`(status/season/category)。

**Tech Stack:** Python 3.9(首行 `from __future__ import annotations`);FastAPI + SQLModel(`select().join(...)`);Jinja2 + Starlette 1.x `TemplateResponse(request, "x.html", {ctx})`;pytest + TestClient。权威设计见 [docs/superpowers/specs/2026-07-02-insights-lanes-health-design.md](../specs/2026-07-02-insights-lanes-health-design.md)。

---

## 文件结构与接口

**新建**
- `app/services/insights.py` —— 只读聚合。接口:
  - `lane_stats(session, *, season_id: Optional[int]=None, category: Optional[Category]=None) -> dict`
  - `overview_counts(session) -> dict`
  - `health_checks(session) -> list[dict]`
- `app/routers/insights.py` —— `GET /insights`(hub)、`GET /lanes`、`GET /health`。
- `app/templates/insights.html`、`lanes.html`、`health.html`。
- `tests/test_insights.py`。

**修改**
- `app/config.py` —— 加 `LANE_MIN_SAMPLE = 10`、`LANE_BIAS_THRESHOLD = 0.5`。
- `app/main.py` —— 注册 `insights.router`。
- `app/templates/base.html` —— 顶栏加 `<a href="/insights">统计</a>`。

**约定**
- 只读铁律:`insights.py` 内不得出现 `session.add`/`session.commit`/`delete`。
- 现有常数:`NUM_LANES = 4`、`MAX_CARS_PER_CATEGORY = 2`(`app/config.py`)。
- 数据链:`HeatResult.heat_id → Heat.id`;`Heat.group_id → Group.id`;`Group.round_id → RaceRound.id`;`RaceRound.race_id → Race.id`。

---

## Task 1: 配置常数

**Files:** Modify `app/config.py`;Test `tests/test_insights.py`(新建)

- [ ] **Step 1: 写失败测试**

创建 `tests/test_insights.py`:

```python
from __future__ import annotations

from sqlmodel import select
from app.enums import Category, TeamType, CarStatus, ProLevel, RaceFormat, RaceStatus
from app.models import (Car, Team, Season, Race, RaceRound, Group, Heat, HeatResult,
                        MarketDraft)
from app.services import seasons as ssvc, teams as tsvc, cars as csvc
from app.services import insights


def test_lane_constants_exist():
    from app import config
    assert config.LANE_MIN_SAMPLE >= 1
    assert config.LANE_BIAS_THRESHOLD > 0
```

- [ ] **Step 2: 运行,确认失败**

Run: `./.venv/bin/python -m pytest tests/test_insights.py::test_lane_constants_exist -v`
Expected: FAIL(`AttributeError: module 'app.config' has no attribute 'LANE_MIN_SAMPLE'`)

- [ ] **Step 3: 加常数**

在 `app/config.py` 的薪资常数区之后追加:

```python
# 赛道公平性(insights)
LANE_MIN_SAMPLE = 10      # 某道场次 < 此数 → 样本不足,不纳入偏差判定
LANE_BIAS_THRESHOLD = 0.5 # 最快/最慢道平均名次差 ≥ 此值 → 提示疑似偏差
```

- [ ] **Step 4: 运行,确认通过**

Run: `./.venv/bin/python -m pytest tests/test_insights.py::test_lane_constants_exist -v`
Expected: PASS(此时 `import insights` 也要成立——若 `app/services/insights.py` 不存在会 ImportError;先建空文件占位)

先建占位文件 `app/services/insights.py`:

```python
from __future__ import annotations
```

- [ ] **Step 5: 提交**

```bash
git add app/config.py app/services/insights.py tests/test_insights.py
git commit -m "feat(insights): 赛道偏差常数 + 服务占位"
```

---

## Task 2: lane_stats

**Files:** Modify `app/services/insights.py`;Test `tests/test_insights.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_insights.py`:

```python
def _finished_heat(session, *, season_id, category, rows, status=RaceStatus.FINISHED):
    """建一场(1 轮 1 组 1 heat)比赛并写入 rows=[(lane, rank, dnf), ...] 的 HeatResult。"""
    race = Race(season_id=season_id, category=category, pro_level=ProLevel.PRO,
                format=RaceFormat.SOLO, status=status)
    session.add(race); session.commit(); session.refresh(race)
    rnd = RaceRound(race_id=race.id, number=1)
    session.add(rnd); session.commit(); session.refresh(rnd)
    grp = Group(round_id=rnd.id, label="A")
    session.add(grp); session.commit(); session.refresh(grp)
    heat = Heat(group_id=grp.id, number=1, recorded=True)
    session.add(heat); session.commit(); session.refresh(heat)
    for lane, rank, dnf in rows:
        session.add(HeatResult(heat_id=heat.id, car_id=1, lane=lane, rank=rank, dnf=dnf))
    session.commit()
    return race


def test_lane_stats_avg_rank_and_rates(session):
    sid = ssvc.start_season(session, name="S1").id
    # 3 车组:1/2/3 道拿 1/2/3
    _finished_heat(session, season_id=sid, category=Category.GT3,
                   rows=[(1, 1, False), (2, 2, False), (3, 3, False)])
    # 4 车组:1/2/3/4 道拿 1/2/3/4,但 1 道这次脱轨(dnf)
    _finished_heat(session, season_id=sid, category=Category.GT3,
                   rows=[(1, None, True), (2, 2, False), (3, 3, False), (4, 4, False)])
    st = insights.lane_stats(session)
    by_lane = {l["lane"]: l for l in st["lanes"]}
    assert st["total_results"] == 7
    # 1 道:2 次出场(1 次拿第一、1 次脱轨)→ avg 只算完赛=1.0,dnf_rate=0.5,win_rate=0.5
    assert by_lane[1]["n"] == 2
    assert abs(by_lane[1]["avg_rank"] - 1.0) < 1e-9
    assert abs(by_lane[1]["dnf_rate"] - 0.5) < 1e-9
    assert abs(by_lane[1]["win_rate"] - 0.5) < 1e-9
    # 4 道:1 次出场 rank4
    assert by_lane[4]["n"] == 1 and abs(by_lane[4]["avg_rank"] - 4.0) < 1e-9


def test_lane_stats_ignores_unfinished_and_filters(session):
    s1 = ssvc.start_season(session, name="S1").id
    _finished_heat(session, season_id=s1, category=Category.GT3, rows=[(1, 1, False)])
    # 进行中比赛不计入
    _finished_heat(session, season_id=s1, category=Category.GT3,
                   rows=[(2, 1, False)], status=RaceStatus.IN_PROGRESS)
    # 另一类别
    _finished_heat(session, season_id=s1, category=Category.F1, rows=[(3, 1, False)])
    assert insights.lane_stats(session)["total_results"] == 2         # 只数已结束
    assert insights.lane_stats(session, category=Category.GT3)["total_results"] == 1
    assert insights.lane_stats(session, season_id=s1, category=Category.F1)["total_results"] == 1


def test_lane_stats_verdict_flags_bias(session):
    sid = ssvc.start_season(session, name="S1").id
    for _ in range(12):   # 每道 ≥ LANE_MIN_SAMPLE
        _finished_heat(session, season_id=sid, category=Category.GT3,
                       rows=[(1, 1, False), (2, 4, False)])
    v = insights.lane_stats(session)["verdict"]
    assert v["enough_sample"] is True
    assert v["biased"] is True
    assert v["fastest_lane"] == 1 and v["slowest_lane"] == 2


def test_lane_stats_empty(session):
    st = insights.lane_stats(session)
    assert st["total_results"] == 0
    assert st["verdict"]["enough_sample"] is False
    assert all(l["avg_rank"] is None for l in st["lanes"])
```

- [ ] **Step 2: 运行,确认失败**

Run: `./.venv/bin/python -m pytest tests/test_insights.py -k lane_stats -v`
Expected: FAIL(`insights` 无 `lane_stats`)

- [ ] **Step 3: 实现 lane_stats**

把 `app/services/insights.py` 写为:

```python
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
```

- [ ] **Step 4: 运行,确认通过**

Run: `./.venv/bin/python -m pytest tests/test_insights.py -k lane_stats -v`
Expected: PASS(4 条)

- [ ] **Step 5: 提交**

```bash
git add app/services/insights.py tests/test_insights.py
git commit -m "feat(insights): lane_stats 赛道公平性聚合"
```

---

## Task 3: overview_counts + health_checks

**Files:** Modify `app/services/insights.py`;Test `tests/test_insights.py`

- [ ] **Step 1: 写失败测试**

追加:

```python
def test_overview_counts(session):
    ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    csvc.create_car(session, nickname="a", category=Category.GT3, brand="X",
                    casting="", description="", team_id=t.id, signed_status=CarStatus.LONG)
    csvc.create_car(session, nickname="b", category=Category.GT3, brand="X",
                    casting="", description="", team_id=None)
    oc = insights.overview_counts(session)
    assert oc["cars"] == 2 and oc["teams"] == 1
    assert oc["active"] == 1 and oc["unsigned"] == 1 and oc["seasons"] == 1


def test_health_all_ok_when_clean(session):
    ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    csvc.create_car(session, nickname="a", category=Category.GT3, brand="X",
                    casting="", description="", team_id=t.id, signed_status=CarStatus.LONG)
    checks = {c["key"]: c for c in insights.health_checks(session)}
    assert all(c["ok"] for c in checks.values())


def test_health_detects_status_inconsistency(session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    # 直接建模型绕过校验:有车队却未签约
    bad = Car(nickname="矛盾", category=Category.GT3, brand="X",
              team_id=t.id, status=CarStatus.UNSIGNED)
    session.add(bad); session.commit()
    c = {x["key"]: x for x in insights.health_checks(session)}["status_consistency"]
    assert c["ok"] is False and any("矛盾" in it["label"] for it in c["items"])
    assert c["items"][0]["href"] == f"/cars/{bad.id}"


def test_health_detects_capacity_over(session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    for i in range(3):   # 直接插 3 辆现役 GT3(绕过服务校验)
        session.add(Car(nickname=f"c{i}", category=Category.GT3, brand="X",
                        team_id=t.id, status=CarStatus.LONG))
    session.commit()
    c = {x["key"]: x for x in insights.health_checks(session)}["capacity"]
    assert c["ok"] is False and any(t.name in it["label"] for it in c["items"])


def test_health_detects_brand_mismatch(session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    session.add(Car(nickname="错牌", category=Category.GT3, brand="保时捷",
                    team_id=t.id, status=CarStatus.LONG))
    session.commit()
    c = {x["key"]: x for x in insights.health_checks(session)}["brand_mismatch"]
    assert c["ok"] is False and any("错牌" in it["label"] for it in c["items"])


def test_health_detects_unfinished_and_draft(session):
    sid = ssvc.start_season(session, name="S1").id
    session.add(Race(season_id=sid, category=Category.GT3, pro_level=ProLevel.PRO,
                     format=RaceFormat.SOLO, status=RaceStatus.IN_PROGRESS))
    session.add(MarketDraft(reference_season_id=sid, tiebreak_seed=1))
    session.commit()
    checks = {x["key"]: x for x in insights.health_checks(session)}
    assert checks["unfinished_races"]["ok"] is False
    assert checks["open_draft"]["ok"] is False
    assert checks["unfinished_races"]["severity"] == "warn"
```

- [ ] **Step 2: 运行,确认失败**

Run: `./.venv/bin/python -m pytest tests/test_insights.py -k "overview or health" -v`
Expected: FAIL(无 `overview_counts`)

- [ ] **Step 3: 实现**

在 `app/services/insights.py` 末尾追加:

```python
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
```

- [ ] **Step 4: 运行,确认通过**

Run: `./.venv/bin/python -m pytest tests/test_insights.py -k "overview or health" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/insights.py tests/test_insights.py
git commit -m "feat(insights): overview_counts + health_checks 健康自检"
```

---

## Task 4: 路由 + 注册

**Files:** Create `app/routers/insights.py`;Modify `app/main.py`;Test `tests/test_insights.py`

- [ ] **Step 1: 写失败测试(仅测路由已注册,不依赖模板)**

追加:

```python
from app.main import app


def test_insights_routes_registered():
    paths = {r.path for r in app.routes}
    assert {"/insights", "/lanes", "/health"} <= paths
```

- [ ] **Step 2: 运行,确认失败**

Run: `./.venv/bin/python -m pytest tests/test_insights.py::test_insights_routes_registered -v`
Expected: FAIL(路由未注册,断言不成立)

- [ ] **Step 3: 建路由**

创建 `app/routers/insights.py`:

```python
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select
from app.db import get_session
from app.models import Season
from app.enums import Category
from app.services import insights
from app.routers.pages import templates

router = APIRouter()


@router.get("/insights", response_class=HTMLResponse)
def insights_hub(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "insights.html", {"request": request})


@router.get("/lanes", response_class=HTMLResponse)
def lanes_page(request: Request, season_id: Optional[int] = None, category: str = "",
               session: Session = Depends(get_session)):
    cat = Category(category) if category else None
    stats = insights.lane_stats(session, season_id=season_id, category=cat)
    seasons = session.exec(select(Season).order_by(Season.id.desc())).all()
    return templates.TemplateResponse(request, "lanes.html", {
        "request": request, "stats": stats, "seasons": seasons,
        "categories": list(Category), "sel_season": season_id, "sel_category": category})


@router.get("/health", response_class=HTMLResponse)
def health_page(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "health.html", {
        "request": request, "overview": insights.overview_counts(session),
        "checks": insights.health_checks(session)})
```

`app/main.py` 现有两行(约 32–39):
```python
from app.routers import pages, cars, teams, seasons, races, standings, market  # noqa: E402
app.include_router(pages.router)
...
app.include_router(market.router)
```
改法:把 import 那行末尾的 `market` 改为 `market, insights`;并在 `app.include_router(market.router)` 之后加一行:
```python
app.include_router(insights.router)
```

- [ ] **Step 4: 运行,确认通过**

Run: `./.venv/bin/python -m pytest tests/test_insights.py::test_insights_routes_registered -v`
Expected: PASS(路由已注册;页面渲染留到 Task 5 建好模板再测)

- [ ] **Step 5: 提交**

```bash
git add app/routers/insights.py app/main.py tests/test_insights.py
git commit -m "feat(insights): /insights /lanes /health 路由 + 注册"
```

---

## Task 5: 模板 + 导航

**Files:** Create `app/templates/{insights,lanes,health}.html`;Modify `app/templates/base.html`;Test 复用 Task 4 的 `test_routes_render`

- [ ] **Step 1: 建 hub 模板**

`app/templates/insights.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h2>统计 / 诊断</h2>
  <div class="row"><a class="btn" href="/lanes">🏁 赛道公平性</a>
    <span><small>各车道平均名次 / 脱轨率,判断实体跑道偏差</small></span></div>
  <div class="row"><a class="btn" href="/health">🩺 健康自检</a>
    <span><small>检查数据是否违反铁律,链到现场手动改</small></span></div>
</div>
{% endblock %}
```

- [ ] **Step 2: 建赛道页模板**

`app/templates/lanes.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h2>赛道公平性</h2>
  <form method="get" action="/lanes" style="margin-bottom:8px">
    <select name="season_id" onchange="this.form.submit()" style="width:auto">
      <option value="">全部赛季</option>
      {% for s in seasons %}
      <option value="{{ s.id }}" {{ 'selected' if sel_season == s.id else '' }}>{{ s.name }}</option>
      {% endfor %}
    </select>
    <select name="category" onchange="this.form.submit()" style="width:auto">
      <option value="">全部类别</option>
      {% for c in categories %}
      <option value="{{ c.value }}" {{ 'selected' if sel_category == c.value else '' }}>{{ c.value }}</option>
      {% endfor %}
    </select>
  </form>

  {% set v = stats.verdict %}
  {% if not v.enough_sample %}
    <p><small>样本不足(各道需 ≥ 阈值场次才判定偏差),以下仅供参考。</small></p>
  {% elif v.biased %}
    <p class="error">疑似偏差:最快 {{ v.fastest_lane }} 道 vs 最慢 {{ v.slowest_lane }} 道,平均名次差 {{ '%.2f'|format(v.spread) }}。</p>
  {% else %}
    <p>未见明显偏差(最快/最慢道平均名次差 {{ '%.2f'|format(v.spread) }})。</p>
  {% endif %}

  <table style="width:100%;border-collapse:collapse;font-size:14px">
    <tr style="border-bottom:1px solid #ddd;text-align:center">
      <th style="text-align:left">车道</th><th>场次</th><th>平均名次</th><th>脱轨率</th><th>拿第一</th>
    </tr>
    {% for l in stats.lanes %}
    <tr style="border-bottom:1px solid #f0f0f0;text-align:center">
      <td style="text-align:left">{{ l.lane }} 道{% if l.low_sample %} <small>(样本不足)</small>{% endif %}</td>
      <td>{{ l.n }}</td>
      <td>{% if l.avg_rank is none %}—{% else %}{{ '%.2f'|format(l.avg_rank) }}{% endif %}</td>
      <td>{{ '%.0f%%'|format(l.dnf_rate * 100) }}</td>
      <td>{{ '%.0f%%'|format(l.win_rate * 100) }}</td>
    </tr>
    {% endfor %}
  </table>
  <p><small>共 {{ stats.total_results }} 条完赛记录纳入统计。平均名次越小越快;脱轨率高=该道爱把车甩飞。</small></p>
</div>
{% endblock %}
```

- [ ] **Step 3: 建健康页模板**

`app/templates/health.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h2>健康自检</h2>
  {% set o = overview %}
  <p><small>车 {{ o.cars }} · 队 {{ o.teams }} · 现役 {{ o.active }} · 退役 {{ o.retired }} · 未签约 {{ o.unsigned }} · 赛季 {{ o.seasons }}</small></p>
  {% if checks | selectattr('ok', 'equalto', false) | list | length == 0 %}
    <p>✅ 一切正常,未发现问题。</p>
  {% endif %}
</div>

{% for c in checks %}
<div class="card">
  <strong>{% if c.ok %}✅{% elif c.severity == 'error' %}❌{% else %}⚠️{% endif %} {{ c.title }}</strong>
  {% if not c.ok %}
  <ul style="margin:6px 0">
    {% for it in c.items %}
    <li><a href="{{ it.href }}">{{ it.label }}</a></li>
    {% endfor %}
  </ul>
  {% endif %}
</div>
{% endfor %}
{% endblock %}
```

- [ ] **Step 4: 导航加入口**

在 `app/templates/base.html` 顶栏 `<a href="/market">转会市场</a>` 之后加一行:

```html
    <a href="/insights">统计</a>
```

- [ ] **Step 5: 加渲染测试并跑全套**

追加到 `tests/test_insights.py`(模板已就位,现在能真正渲染):

```python
from fastapi.testclient import TestClient

_client = TestClient(app)


def test_routes_render(engine, session):
    sid = ssvc.start_season(session, name="S1").id
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    csvc.create_car(session, nickname="a", category=Category.GT3, brand="X",
                    casting="", description="", team_id=t.id, signed_status=CarStatus.LONG)
    assert _client.get("/insights").status_code == 200
    r = _client.get("/lanes")
    assert r.status_code == 200 and "平均名次" in r.text
    assert _client.get("/lanes", params={"category": "GT3", "season_id": sid}).status_code == 200
    h = _client.get("/health")
    assert h.status_code == 200 and "状态一致性" in h.text
```

Run: `./.venv/bin/python -m pytest tests/test_insights.py -v`
Expected: 全部 PASS(含 `test_routes_render`)。
Run: `./.venv/bin/python -m pytest -q 2>&1 | grep -iE "passed|failed"`
Expected: 全绿(既有 + 新增)。

- [ ] **Step 6: 守护数据库 + 提交**

```bash
git status --short data/hotwheel.db  # 若被改:git checkout -- data/hotwheel.db
git add app/templates/insights.html app/templates/lanes.html app/templates/health.html app/templates/base.html tests/test_insights.py
git commit -m "feat(insights): 统计/诊断三页模板 + 导航入口"
```

---

## 自查(计划对照 spec)

- §3.1 数据源/筛选(已结束比赛、season/category)→ Task 2 `lane_stats` + Task 4 路由参数。
- §3.2 指标(n/avg_rank 只算完赛/dnf_rate/win_rate)→ Task 2,测试 `test_lane_stats_avg_rank_and_rates`。
- §3.3 判定(样本阈值、偏差阈值、fastest/slowest)→ Task 2,测试 `test_lane_stats_verdict_flags_bias`。
- §3.4 返回结构 → Task 2 返回 dict 与 spec 字段一致。
- §3.5 页面(筛选、表、verdict)→ Task 5 `lanes.html`。
- §4.1 概览计数 → Task 3 `overview_counts`。
- §4.2 五项检查(3 error + 2 warn,含 href)→ Task 3 `health_checks`,逐项测试。
- §4.3 页面(卡片、✅/❌/⚠️、全绿提示)→ Task 5 `health.html`。
- §5 服务/文件边界、config 常数、main 注册、nav → Task 1/3/4/5。
- §6 测试要点 → 分散在 Task 2/3/4 测试。
- §7 只读铁律 → `insights.py` 无 add/commit(评审核查);空库 → Task 2 `test_lane_stats_empty`。
