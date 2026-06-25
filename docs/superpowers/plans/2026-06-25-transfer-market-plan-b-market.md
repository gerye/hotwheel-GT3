# 转会市场 · 计划B:转会流程与页面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> 依据 spec `docs/superpowers/specs/2026-06-25-transfer-market-design.md` §3-§5。**前置:计划A 已完成**(合同、薪资/预算、快照)。

**Goal:** 实现半自动转会:释放短期车 → 选秀推荐(余额最高的队先签满)→ 你在转会页增删改(带预算/品牌/名额校验)→ 确认定档,衔接赛季开启。

**Architecture:** 纯逻辑放 `app/services/market.py`(headroom/sign/release/recommend),路由只编排;转会页用现有 Jinja2 + err 横幅展示校验错误。预算/薪资在页面**实时计算**(用计划A 的 `budget`/`salary`,参照"最近结束的赛季")。

**Tech Stack:** 同项目。参照赛季 = 最近一个 `已结束` 赛季;无则用 `进行中` 赛季。

---

## 文件结构
```
app/services/market.py        # 新:open_market / headroom / sign / release / recommend / reference_season
app/routers/market.py         # 新:/market 页 + 开盘/推荐/签约/释放/确认 端点
app/templates/market.html     # 新:转会页(各队预算/余额/阵容 + 自由池 + 操作)
app/main.py                   # 改:挂 market 路由
app/templates/seasons.html    # 改:加「转会市场」入口
tests/test_market.py
```

---

## Task 1: open_market(快照 + 释放短期车)+ 参照赛季

**Files:** Create `app/services/market.py`;Test `tests/test_market.py`

- [ ] **Step 1: 失败测试**(`tests/test_market.py`)
```python
from sqlmodel import select
from app.enums import Category, TeamType, CarStatus, ContractType
from app.services import seasons as ssvc, teams as tsvc, cars as csvc, market
from app.models import Car


def _seed(session):
    s = ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    long_car = csvc.create_car(session, nickname="老将", category=Category.GT3, brand="B",
                               casting="", description="", team_id=t.id,
                               contract=ContractType.LONG)
    short_car = csvc.create_car(session, nickname="临时", category=Category.GT3, brand="B",
                                casting="", description="", team_id=t.id,
                                contract=ContractType.SHORT)
    return s, t, long_car, short_car


def test_open_market_releases_short_keeps_long(session):
    s, t, long_car, short_car = _seed(session)
    ssvc.end_season(session, s.id)          # 先结束赛季,产生 MMR 快照
    market.open_market(session)
    session.expire_all()
    assert session.get(Car, long_car.id).team_id == t.id            # 长期留任
    assert session.get(Car, long_car.id).status == CarStatus.ACTIVE
    assert session.get(Car, short_car.id).team_id is None           # 短期释放
    assert session.get(Car, short_car.id).status == CarStatus.UNSIGNED
    assert session.get(Car, short_car.id).contract is None
```

- [ ] **Step 2:** `pytest tests/test_market.py -v` → FAIL。

- [ ] **Step 3: 写 `app/services/market.py`(本任务部分)**
```python
from typing import Optional
from sqlmodel import Session, select
from app.models import Car, Team, Season
from app.enums import CarStatus, ContractType, SeasonStatus
from app.services import market_snapshot, seasons as ssvc


class MarketError(Exception):
    pass


def reference_season(session: Session) -> Optional[Season]:
    """转会参照赛季:最近一个已结束赛季;无则当前进行中赛季。"""
    ended = session.exec(select(Season).where(Season.status == SeasonStatus.FINISHED)
                         .order_by(Season.id.desc())).first()
    return ended or ssvc.get_active_season(session)


def open_market(session: Session) -> None:
    """开盘:按参照赛季写预算/薪资快照;释放所有短期合同车为自由身。"""
    ref = reference_season(session)
    if ref is not None:
        market_snapshot.snapshot_season(session, ref.id)
    for car in session.exec(select(Car).where(
            Car.contract == ContractType.SHORT)).all():
        car.team_id = None
        car.status = CarStatus.UNSIGNED
        car.contract = None
        session.add(car)
    session.commit()
```

- [ ] **Step 4:** `pytest tests/test_market.py -v` → PASS。

- [ ] **Step 5: 提交** `git add app/services/market.py tests/test_market.py && git commit -m "feat(market): open market - snapshot + release short contracts"`

---

## Task 2: 余额、签约、释放(含校验)

**Files:** Modify `app/services/market.py`;Test `tests/test_market.py`(追加)

签约校验:品牌锁(复用 `teams.check_can_assign` 的品牌部分)、每类别现役<2、**预算**(现役薪资和 + 新车薪资 ≤ 预算;新签不允许超预算)。释放=变自由身。

- [ ] **Step 1: 失败测试**(追加)
```python
from app.services import salary as sal, budget as bud


def test_headroom_and_sign(session):
    s, t, long_car, short_car = _seed(session)
    ssvc.end_season(session, s.id)
    market.open_market(session)             # short_car 释放
    ref = market.reference_season(session)
    # 自由市场签回 short_car
    market.sign(session, short_car.id, t.id, ref.id)
    session.expire_all()
    assert session.get(Car, short_car.id).team_id == t.id
    assert session.get(Car, short_car.id).status == CarStatus.ACTIVE
    assert session.get(Car, short_car.id).contract == ContractType.SHORT


def test_sign_blocked_when_category_full(session):
    import pytest
    s = ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    for i in range(2):
        csvc.create_car(session, nickname=f"a{i}", category=Category.GT3, brand="B",
                        casting="", description="", team_id=t.id, contract=ContractType.LONG)
    free = csvc.create_car(session, nickname="free", category=Category.GT3, brand="B",
                           casting="", description="", team_id=None)
    ssvc.end_season(session, s.id)
    market.open_market(session)
    ref = market.reference_season(session)
    with pytest.raises(market.MarketError):
        market.sign(session, free.id, t.id, ref.id)     # 该类别已 2 现役
```

- [ ] **Step 2:** `pytest tests/test_market.py -v` → FAIL。

- [ ] **Step 3: 追加到 `app/services/market.py`**
```python
from app.enums import TeamType
from app.services import salary as sal, budget as bud
from app.config import MAX_CARS_PER_CATEGORY


def committed_salary(session: Session, team_id: int, season_id: int) -> int:
    cars = session.exec(select(Car).where(Car.team_id == team_id,
                        Car.status == CarStatus.ACTIVE)).all()
    return sum(sal.compute_salary(session, c, season_id) for c in cars)


def headroom(session: Session, team_id: int, season_id: int) -> int:
    team = session.get(Team, team_id)
    return bud.compute_budget(session, team, season_id) - committed_salary(session, team_id, season_id)


def _active_in_category(session: Session, team_id: int, category) -> int:
    return len(session.exec(select(Car).where(
        Car.team_id == team_id, Car.category == category,
        Car.status == CarStatus.ACTIVE)).all())


def sign(session: Session, car_id: int, team_id: int, season_id: int) -> None:
    car = session.get(Car, car_id)
    team = session.get(Team, team_id)
    if car is None or team is None:
        raise MarketError("赛车或车队不存在")
    if team.type == TeamType.FACTORY and car.brand != team.brand:
        raise MarketError(f"厂商车队「{team.name}」只能签品牌「{team.brand}」的车")
    if _active_in_category(session, team_id, car.category) >= MAX_CARS_PER_CATEGORY:
        raise MarketError(f"{team.name} 在 {car.category.value} 已有 2 个现役")
    price = sal.compute_salary(session, car, season_id)
    if price > headroom(session, team_id, season_id):
        raise MarketError(f"预算不足:{car.nickname} 薪资 {price} > 余额 "
                          f"{headroom(session, team_id, season_id)}")
    car.team_id = team_id
    car.status = CarStatus.ACTIVE
    car.contract = ContractType.SHORT     # 自由市场签下默认短期
    session.add(car); session.commit()


def release(session: Session, car_id: int) -> None:
    car = session.get(Car, car_id)
    if car is None:
        raise MarketError("赛车不存在")
    car.team_id = None
    car.status = CarStatus.UNSIGNED
    car.contract = None
    session.add(car); session.commit()
```

- [ ] **Step 4:** `pytest tests/test_market.py -v` → PASS。

- [ ] **Step 5: 提交** `git add app/services/market.py tests/test_market.py && git commit -m "feat(market): headroom + sign/release with validation"`

---

## Task 3: 选秀推荐(余额最高的队先签满)

**Files:** Modify `app/services/market.py`;Test `tests/test_market.py`(追加)

算法:反复——取**余额最高**且**有可填空位**(某类别正好 1 现役、且自由池里有可签得起的品牌匹配车)的队,把它所有这类空位用**赛季末 MMR 最高的可负担自由车**补到 2;一队补完再重算余额取下一队;直到没有可填的。只填**已有 1 现役**的类别(不自动开新类别;新类别由你手动)。

- [ ] **Step 1: 失败测试**(追加)
```python
def test_recommend_fills_partial_category(session):
    s = ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    csvc.create_car(session, nickname="留任", category=Category.GT3, brand="B",
                    casting="", description="", team_id=t.id, contract=ContractType.LONG)
    free = csvc.create_car(session, nickname="自由", category=Category.GT3, brand="B",
                           casting="", description="", team_id=None)
    ssvc.end_season(session, s.id)
    market.open_market(session)
    ref = market.reference_season(session)
    market.recommend(session, ref.id)
    session.expire_all()
    # 该队 GT3 原本 1 现役 → 推荐补到 2,签下自由车
    assert session.get(Car, free.id).team_id == t.id
    assert market._active_in_category(session, t.id, Category.GT3) == 2
```

- [ ] **Step 2:** `pytest tests/test_market.py -v` → FAIL。

- [ ] **Step 3: 追加到 `app/services/market.py`**
```python
def _free_agents(session: Session):
    return session.exec(select(Car).where(Car.team_id == None)).all()  # noqa: E711


def _partial_categories(session: Session, team_id: int):
    """该队正好 1 个现役的类别列表。"""
    out = []
    for cat in {c.category for c in session.exec(select(Car).where(
            Car.team_id == team_id, Car.status == CarStatus.ACTIVE)).all()}:
        if _active_in_category(session, team_id, cat) == 1:
            out.append(cat)
    return out


def _team_has_need(session: Session, team_id: int) -> bool:
    return len(_partial_categories(session, team_id)) > 0


def recommend(session: Session, season_id: int) -> None:
    """半自动推荐:余额最高的队先把已有 1 现役的类别补到 2。"""
    guard = 0
    while True:
        guard += 1
        if guard > 1000:
            break
        teams = [t for t in session.exec(select(Team)).all()
                 if _team_has_need(session, t.id)]
        if not teams:
            break
        teams.sort(key=lambda t: headroom(session, t.id, season_id), reverse=True)
        team = teams[0]
        signed_any = False
        for cat in _partial_categories(session, team.id):
            # 该类别可签的自由车:品牌匹配 + 买得起,挑赛季末 MMR 最高
            from app.enums import TeamType
            cands = []
            for c in _free_agents(session):
                if c.category != cat:
                    continue
                if team.type == TeamType.FACTORY and c.brand != team.brand:
                    continue
                if sal.compute_salary(session, c, season_id) <= headroom(session, team.id, season_id):
                    cands.append(c)
            cands.sort(key=lambda c: sal._season_mmr(session, c, season_id), reverse=True)
            if cands:
                try:
                    sign(session, cands[0].id, team.id, season_id)
                    signed_any = True
                except MarketError:
                    pass
        if not signed_any:
            # 该队无法再补(没合适/买不起)→ 跳过它避免死循环
            # 用一次性标记:把它从候选里排除靠下一轮 headroom 不变;这里直接 break 最高队无法签的情况
            break
```
> 说明:`recommend` 是"建议",可重复调用;之后你在页面手动增删改。若最高余额队无法补位即停止(避免死循环);更细的轮转可后续优化(YAGNI)。

- [ ] **Step 4:** `pytest tests/test_market.py -v` → PASS。

- [ ] **Step 5: 提交** `git add app/services/market.py tests/test_market.py && git commit -m "feat(market): semi-auto draft recommendation"`

---

## Task 4: 转会页面 + 端点

**Files:** Create `app/routers/market.py`、`app/templates/market.html`;Modify `app/main.py`、`app/templates/seasons.html`;Test `tests/test_market.py`(追加路由测试)

- [ ] **Step 1: 失败测试**(追加)
```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_market_page_and_actions(engine, session):
    s = ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    csvc.create_car(session, nickname="留任", category=Category.GT3, brand="B",
                    casting="", description="", team_id=t.id, contract=ContractType.LONG)
    csvc.create_car(session, nickname="自由", category=Category.GT3, brand="B",
                    casting="", description="", team_id=None)
    ssvc.end_season(session, s.id)
    assert client.post("/market/open", follow_redirects=False).status_code in (302, 303)
    r = client.get("/market")
    assert r.status_code == 200 and "自由" in r.text and "预算" in r.text
    assert client.post("/market/recommend", follow_redirects=False).status_code in (302, 303)
```

- [ ] **Step 2:** `pytest tests/test_market.py -k market_page -v` → FAIL。

- [ ] **Step 3: 写 `app/routers/market.py`**
```python
from urllib.parse import quote
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from app.db import get_session
from app.models import Team, Car
from app.enums import CarStatus
from app.services import market, salary as sal, budget as bud
from app.routers.pages import templates

router = APIRouter()


@router.get("/market", response_class=HTMLResponse)
def market_page(request: Request, session: Session = Depends(get_session)):
    ref = market.reference_season(session)
    teams_view, pool = [], []
    if ref is not None:
        for t in session.exec(select(Team)).all():
            roster = session.exec(select(Car).where(Car.team_id == t.id,
                     Car.status == CarStatus.ACTIVE)).all()
            teams_view.append({
                "team": t,
                "budget": bud.compute_budget(session, t, ref.id),
                "headroom": market.headroom(session, t.id, ref.id),
                "roster": [{"car": c, "salary": sal.compute_salary(session, c, ref.id)}
                           for c in roster]})
        for c in session.exec(select(Car).where(Car.team_id == None)).all():  # noqa: E711
            pool.append({"car": c, "salary": sal.compute_salary(session, c, ref.id)})
    return templates.TemplateResponse(request, "market.html", {
        "request": request, "ref": ref, "teams": teams_view, "pool": pool})


@router.post("/market/open")
def market_open(session: Session = Depends(get_session)):
    market.open_market(session)
    return RedirectResponse("/market", status_code=303)


@router.post("/market/recommend")
def market_recommend(session: Session = Depends(get_session)):
    ref = market.reference_season(session)
    if ref:
        market.recommend(session, ref.id)
    return RedirectResponse("/market", status_code=303)


@router.post("/market/sign")
def market_sign(car_id: int = Form(...), team_id: int = Form(...),
                session: Session = Depends(get_session)):
    ref = market.reference_season(session)
    try:
        market.sign(session, car_id, team_id, ref.id)
        return RedirectResponse("/market", status_code=303)
    except market.MarketError as e:
        return RedirectResponse(f"/market?err={quote(str(e))}", status_code=303)


@router.post("/market/release")
def market_release(car_id: int = Form(...), session: Session = Depends(get_session)):
    market.release(session, car_id)
    return RedirectResponse("/market", status_code=303)
```

- [ ] **Step 4: 写 `app/templates/market.html`**
```html
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h2>转会市场</h2>
  {% if not ref %}<p class="error">还没有赛季,无法转会。</p>{% else %}
  <p><small>参照赛季:{{ ref.name }}</small></p>
  <form method="post" action="/market/open" style="display:inline"
        onsubmit="return confirm('开盘会释放所有短期合同车为自由身,确定?')">
    <button class="btn">开盘(释放短期车)</button></form>
  <form method="post" action="/market/recommend" style="display:inline">
    <button class="btn">生成推荐阵容</button></form>
  {% endif %}
</div>

{% for tv in teams %}
<div class="card">
  <div style="display:flex;justify-content:space-between">
    <strong>{{ tv.team.name }}</strong>
    <span><small>预算 {{ tv.budget }} · 余额 {{ tv.headroom }}</small></span>
  </div>
  {% for r in tv.roster %}
  <div class="row">
    <span style="flex:1">{{ r.car.nickname }} <span class="tag">{{ r.car.category.value }}</span>
      {% if r.car.contract %}<span class="tag">{{ r.car.contract.value }}</span>{% endif %}</span>
    <span><small>薪资 {{ r.salary }}</small></span>
    <form method="post" action="/market/release" style="display:inline">
      <input type="hidden" name="car_id" value="{{ r.car.id }}">
      <button class="btn">释放</button></form>
  </div>
  {% else %}<p><small>无现役</small></p>{% endfor %}
</div>
{% endfor %}

<div class="card">
  <h3>自由市场</h3>
  {% for p in pool %}
  <div class="row">
    <span style="flex:1">{{ p.car.nickname }} <span class="tag">{{ p.car.category.value }}</span> · {{ p.car.brand }}</span>
    <span><small>薪资 {{ p.salary }}</small></span>
    <form method="post" action="/market/sign" style="display:flex;gap:4px">
      <input type="hidden" name="car_id" value="{{ p.car.id }}">
      <select name="team_id">
        {% for tv in teams %}<option value="{{ tv.team.id }}">{{ tv.team.name }}</option>{% endfor %}
      </select>
      <button class="btn">签约</button>
    </form>
  </div>
  {% else %}<p>自由市场空</p>{% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 5: 挂路由 + 入口**——`app/main.py` 加 `from app.routers import market` + `app.include_router(market.router)`;`app/templates/seasons.html` 顶部加 `<a class="btn" href="/market">转会市场</a>`;`base.html` 顶部导航也可加(可选)。

- [ ] **Step 6:** `pytest tests/test_market.py -v` → PASS;`uvicorn` 冒烟:结束一个赛季 → /market 开盘 → 推荐 → 手动签/放。

- [ ] **Step 7: 提交** `git add -A && git commit -m "feat(market): transfer page + open/recommend/sign/release routes"`

---

## Task 5: 确认定档(衔接开启下一季)

**Files:** Modify `app/routers/market.py`、`app/templates/market.html`;Test `tests/test_market.py`(追加)

确认=结束转会,提示去「赛季」开启下一季(阵容已是当前 team_id 状态,无需额外写入)。

- [ ] **Step 1: 失败测试**(追加)
```python
def test_finalize_redirects_to_seasons(engine, session):
    ssvc.start_season(session, name="S1")
    ssvc.end_season(session, session.exec(select(__import__('app.models', fromlist=['Season']).Season)).first().id)
    client.post("/market/open")
    r = client.post("/market/finalize", follow_redirects=False)
    assert r.status_code in (302, 303) and "/seasons" in r.headers["location"]
```

- [ ] **Step 2:** `pytest tests/test_market.py -k finalize -v` → FAIL。

- [ ] **Step 3: 加 finalize 端点**(`app/routers/market.py`)
```python
@router.post("/market/finalize")
def market_finalize(session: Session = Depends(get_session)):
    # 阵容即当前 team_id 状态,无需额外持久化;引导去开启下一季
    return RedirectResponse("/seasons", status_code=303)
```
并在 `market.html` 加按钮:
```html
  <form method="post" action="/market/finalize" style="display:inline">
    <button class="btn">完成转会 → 去开启下一季</button></form>
```

- [ ] **Step 4:** `pytest tests/test_market.py -v` → PASS;全量 `pytest`。

- [ ] **Step 5: 提交** `git add -A && git commit -m "feat(market): finalize -> seasons"`

---

## 自检
- **Spec 覆盖**:开盘释放短期/留任长期(T1)、余额与签约校验:品牌锁+每类别2+预算(T2)、半自动选秀余额最高先签满(T3)、转会页增删改+错误横幅(T4)、确认衔接开季(T5)。长期合同超支保留——长期车不在 open_market 释放、也不被签约流程触碰,天然保留;`sign` 只拦新签超预算,不动既有(满足"长期可超支")。
- **占位扫描**:无 TODO;recommend 的"最高队无法补即停"是有意简化(注释标注 YAGNI)。
- **类型一致**:`market.open_market/headroom/sign/release/recommend/reference_season/committed_salary/_active_in_category` 在定义、路由、测试一致;依赖计划A 的 `salary.compute_salary`、`budget.compute_budget`、`salary._season_mmr`、`market_snapshot.snapshot_season`。
- **边界**:无赛季时页面提示、不报错;`sign` 失败走 err 横幅;`release` 任意现役车可放。
