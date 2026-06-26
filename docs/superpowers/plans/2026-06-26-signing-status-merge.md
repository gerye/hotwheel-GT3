# 合并签约状态实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把赛车的「状态(未签约/现役/退役)+ 合约(长期/短期)」合并为单一 `CarStatus`(未签约/长期合约/短期合约/退役),删除 `ContractType` 与 `Car.contract`。

**Architecture:** `CarStatus` 扩为 4 值,「现役」改为 `状态∈{长期,短期}`(辅助 `is_active`/`ACTIVE_STATUSES`)。所有 `==CarStatus.ACTIVE` 改为成员判断;签约/换队/复出时落具体合约状态;开盘按 `status==短期合约` 释放。现有数据用原始 SQL 一次性把 `'ACTIVE'→'LONG'`。

**Tech Stack:** Python 3.9 / FastAPI / SQLModel / SQLite / pytest。运行用 `.venv/Scripts/python.exe`。

参照设计 spec:`docs/superpowers/specs/2026-06-26-signing-status-merge-design.md`。

---

## 文件结构

- `app/enums.py` — `CarStatus` 改 4 值 + `is_active`/`ACTIVE_STATUSES`;删 `ContractType`。
- `app/models.py` — 删 `Car.contract` 与 import。
- `app/db.py` — 启动迁移 `'ACTIVE'→'LONG'`。
- `app/services/cars.py` — `create_car`/`update_car`/`change_status` 改用签约状态。
- `app/services/teams.py` — `active_count` 用 `ACTIVE_STATUSES`。
- `app/services/tournament.py` — 专业赛资格、`_team_cars` 用 `ACTIVE_STATUSES`。
- `app/services/market.py` — 开盘/签约/统计改用状态。
- `app/routers/cars.py`、`app/routers/market.py`、`app/routers/races.py`、`app/routers/teams.py` — 表单参数与现役判断。
- `app/templates/car_form.html`、`_car_rows.html`、`car_detail.html`、`market.html` — 显示与录入。
- `tests/*` — 更新 `ContractType`/`ACTIVE` 引用,新增状态机/开盘/资格用例。

运行全套测试命令贯穿始终:`.venv/Scripts/python.exe -m pytest -q`

---

## Task 1: 枚举与模型(单一签约状态)

**Files:**
- Modify: `app/enums.py:12-15`(CarStatus)、`app/enums.py:43-45`(删 ContractType)
- Modify: `app/models.py:6`、`app/models.py:50`(删 contract)
- Test: `tests/test_enums_status.py`(新建)

- [ ] **Step 1: 写失败测试**

`tests/test_enums_status.py`:
```python
from app.enums import CarStatus, ACTIVE_STATUSES


def test_four_values():
    assert [s.value for s in CarStatus] == ["未签约", "长期合约", "短期合约", "退役"]


def test_is_active():
    assert CarStatus.LONG.is_active and CarStatus.SHORT.is_active
    assert not CarStatus.UNSIGNED.is_active and not CarStatus.RETIRED.is_active
    assert set(ACTIVE_STATUSES) == {CarStatus.LONG, CarStatus.SHORT}


def test_contract_type_removed():
    import app.enums as e
    assert not hasattr(e, "ContractType")
```

- [ ] **Step 2: 运行,确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_enums_status.py -q`
Expected: FAIL(ImportError: ACTIVE_STATUSES / 值不符)

- [ ] **Step 3: 改 `app/enums.py`**

把 `CarStatus` 整段替换为:
```python
class CarStatus(str, Enum):
    UNSIGNED = "未签约"
    LONG = "长期合约"
    SHORT = "短期合约"
    RETIRED = "退役"

    @property
    def is_active(self) -> bool:
        return self in (CarStatus.LONG, CarStatus.SHORT)


ACTIVE_STATUSES = (CarStatus.LONG, CarStatus.SHORT)
```
删除整段 `class ContractType(str, Enum): ...`(43-45)。

- [ ] **Step 4: 改 `app/models.py`**

第 6 行 import 去掉 `ContractType`:
```python
from app.enums import Category, TeamType, SeasonStatus, CarStatus
```
删除第 50 行 `contract: Optional[ContractType] = None   # 仅有车队时有意义`。

- [ ] **Step 5: 运行新测试,确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_enums_status.py -q`
Expected: PASS(其余模块此时仍引用旧符号,先不跑全套)

- [ ] **Step 6: 提交**

```bash
git add app/enums.py app/models.py tests/test_enums_status.py
git commit -m "refactor(status): CarStatus 改 4 值并删除 ContractType"
```

---

## Task 2: 现役判断改为成员判断(服务+路由)

把所有「等于 `CarStatus.ACTIVE`」改成「∈ `ACTIVE_STATUSES`」,并清掉 `contract` 的读写(签约状态承载之)。

**Files:**
- Modify: `app/services/teams.py:110`、`app/services/tournament.py:25,302`、
  `app/services/market.py:6,27,30,42,54,74-75,84-85`、
  `app/routers/market.py:23`、`app/routers/races.py:22,30`、`app/routers/teams.py:83`

- [ ] **Step 1: `app/services/teams.py`**

第 110 行 `active_count` 内:
```python
Car.status.in_(ACTIVE_STATUSES))
```
文件顶部 import 增加 `ACTIVE_STATUSES`:`from app.enums import TeamType, Category, CarStatus, ACTIVE_STATUSES`。

- [ ] **Step 2: `app/services/tournament.py`**

import 增加 `ACTIVE_STATUSES`(与现有 `from app.enums import ...` 合并)。
第 25 行:
```python
if car is not None and not car.status.is_active:
    raise ValueError("专业赛只能选择现役(长期/短期)赛车")
```
第 302 行 `_team_cars`:
```python
Car.status.in_(ACTIVE_STATUSES))).all()]   # 只派现役车手出战
```

- [ ] **Step 3: `app/services/market.py`**

第 6 行 import 改为:`from app.enums import CarStatus, SeasonStatus, ACTIVE_STATUSES`(去掉 `ContractType`)。
开盘释放(27-31)整段改为:
```python
    for car in session.exec(select(Car).where(
            Car.status == CarStatus.SHORT)).all():
        car.team_id = None
        car.status = CarStatus.UNSIGNED
        session.add(car)
```
第 42 行、第 54 行、第 97 行的 `Car.status == CarStatus.ACTIVE` → `Car.status.in_(ACTIVE_STATUSES)`。
`sign`(74-75)签约落短期、删 contract:
```python
    car.team_id = team_id
    car.status = CarStatus.SHORT          # 自由市场签下默认短期合约
```
`release`(84-85):
```python
    car.team_id = None
    car.status = CarStatus.UNSIGNED
```

- [ ] **Step 4: 路由现役判断**

`app/routers/market.py:23`:`Car.status.in_(ACTIVE_STATUSES))).all())`(import 加 `ACTIVE_STATUSES`)。
`app/routers/races.py:22`:`cars = [c for c in cars if c.status.is_active]`;
`app/routers/races.py:30`:`Car.status.in_(ACTIVE_STATUSES),`(import 加 `ACTIVE_STATUSES`)。
`app/routers/teams.py:83`:`if c.status.is_active:`。

- [ ] **Step 5: 暂不跑全套(create/update_car 仍引用 contract,下个任务修)。提交**

```bash
git add app/services/teams.py app/services/tournament.py app/services/market.py app/routers/market.py app/routers/races.py app/routers/teams.py
git commit -m "refactor(status): 现役判断改为 ACTIVE_STATUSES 成员判断"
```

---

## Task 3: 状态机 `change_status`(4 值转换)

**Files:**
- Modify: `app/services/cars.py:121-149`
- Test: `tests/test_status_machine.py`(新建)

- [ ] **Step 1: 写失败测试**

`tests/test_status_machine.py`:
```python
import pytest
from sqlmodel import select
from app.enums import Category, CarStatus, TeamType
from app.services import seasons as ssvc, teams as tsvc, cars as csvc
from app.models import Car


def _team(session, name="t"):
    return tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name=name)


def test_long_short_toggle(session):
    t = _team(session)
    c = csvc.create_car(session, nickname="a", category=Category.GT3, brand="B",
                        casting="", description="", team_id=t.id,
                        signed_status=CarStatus.LONG)
    csvc.change_status(session, c.id, CarStatus.SHORT)
    assert session.get(Car, c.id).status == CarStatus.SHORT


def test_retire_then_comeback_pick_contract(session):
    t = _team(session)
    c = csvc.create_car(session, nickname="b", category=Category.GT3, brand="B",
                        casting="", description="", team_id=t.id,
                        signed_status=CarStatus.LONG)
    csvc.change_status(session, c.id, CarStatus.RETIRED)
    assert session.get(Car, c.id).status == CarStatus.RETIRED
    csvc.change_status(session, c.id, CarStatus.SHORT)   # 复出选短期
    assert session.get(Car, c.id).status == CarStatus.SHORT


def test_unsigned_cannot_sign_directly(session):
    c = csvc.create_car(session, nickname="c", category=Category.GT3, brand="B",
                        casting="", description="", team_id=None)
    with pytest.raises(csvc.CarValidationError):
        csvc.change_status(session, c.id, CarStatus.LONG)


def test_comeback_blocked_when_full(session):
    t = _team(session)
    for i in range(2):
        csvc.create_car(session, nickname=f"x{i}", category=Category.GT3, brand="B",
                        casting="", description="", team_id=t.id,
                        signed_status=CarStatus.LONG)
    r = csvc.create_car(session, nickname="r", category=Category.GT3, brand="B",
                        casting="", description="", team_id=t.id,
                        signed_status=CarStatus.LONG)
    csvc.change_status(session, r.id, CarStatus.RETIRED)   # 现 2 现役
    with pytest.raises(tsvc.TeamValidationError):
        csvc.change_status(session, r.id, CarStatus.LONG)  # 名额满,复出失败
```

- [ ] **Step 2: 运行,确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_status_machine.py -q`
Expected: FAIL(`signed_status` 参数未知 / 转换未实现)

- [ ] **Step 3: 改 `change_status`(替换 121-149 整段函数体)**

```python
def change_status(session: Session, car_id: int, new_status: CarStatus) -> Car:
    """按状态机切换签约状态(含条件校验)。"""
    car = session.get(Car, car_id)
    if car is None:
        raise CarValidationError("赛车不存在")
    if new_status == car.status:
        return car
    if new_status == CarStatus.UNSIGNED:
        car.team_id = None
        car.status = CarStatus.UNSIGNED
    elif new_status == CarStatus.RETIRED:
        if not car.status.is_active:
            raise CarValidationError("只有现役(长期/短期)赛车才能退役")
        car.status = CarStatus.RETIRED
    elif new_status in (CarStatus.LONG, CarStatus.SHORT):
        if car.status == CarStatus.UNSIGNED:
            raise CarValidationError("不能直接签约,请先在「编辑」里加入车队")
        team = session.get(Team, car.team_id) if car.team_id else None
        if team is None:
            raise CarValidationError("该赛车没有车队")
        if car.status == CarStatus.RETIRED:        # 复出 → 需现役名额未满
            tsvc.check_active_capacity(session, team=team, category=car.category,
                                       exclude_car_id=car.id)
        car.status = new_status                     # 长↔短 或 复出落具体合约
    session.add(car)
    session.commit()
    session.refresh(car)
    return car
```

(注:`create_car` 的 `signed_status` 参数在 Task 4 实现;本任务测试依赖它,故 Task 3、4 连续完成后再跑绿。)

- [ ] **Step 4: 提交(待 Task 4 后统一跑绿)**

```bash
git add app/services/cars.py tests/test_status_machine.py
git commit -m "refactor(status): change_status 支持长期/短期/退役/复出"
```

---

## Task 4: 创建/编辑赛车与表单(合约即状态)

**Files:**
- Modify: `app/services/cars.py:21-39`(create_car)、`:82-117`(update_car)
- Modify: `app/routers/cars.py:13,42-59,72-94`
- Modify: `app/templates/car_form.html:27-32`
- Test: `tests/test_cars_signing.py`(新建)

- [ ] **Step 1: 写失败测试**

`tests/test_cars_signing.py`:
```python
from app.enums import Category, CarStatus, TeamType
from app.services import teams as tsvc, cars as csvc
from app.models import Car


def _team(session):
    return tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="t")


def test_create_with_team_uses_signed_status(session):
    t = _team(session)
    c = csvc.create_car(session, nickname="a", category=Category.GT3, brand="B",
                        casting="", description="", team_id=t.id,
                        signed_status=CarStatus.SHORT)
    assert session.get(Car, c.id).status == CarStatus.SHORT


def test_create_without_team_unsigned(session):
    c = csvc.create_car(session, nickname="b", category=Category.GT3, brand="B",
                        casting="", description="", team_id=None)
    assert c.status == CarStatus.UNSIGNED


def test_edit_change_contract(session):
    t = _team(session)
    c = csvc.create_car(session, nickname="c", category=Category.GT3, brand="B",
                        casting="", description="", team_id=t.id,
                        signed_status=CarStatus.LONG)
    csvc.update_car(session, c.id, team_id=t.id, signed_status=CarStatus.SHORT)
    assert session.get(Car, c.id).status == CarStatus.SHORT


def test_edit_keeps_retired(session):
    t = _team(session)
    c = csvc.create_car(session, nickname="d", category=Category.GT3, brand="B",
                        casting="", description="", team_id=t.id,
                        signed_status=CarStatus.LONG)
    csvc.change_status(session, c.id, CarStatus.RETIRED)
    csvc.update_car(session, c.id, team_id=t.id, signed_status=CarStatus.LONG,
                    casting="x")
    assert session.get(Car, c.id).status == CarStatus.RETIRED   # 编辑不改变退役
```

- [ ] **Step 2: 运行,确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cars_signing.py -q`
Expected: FAIL(`signed_status` 未支持)

- [ ] **Step 3: 改 `create_car`(21-39)**

签名把 `contract: Optional[ContractType] = None` 换为 `signed_status: CarStatus = CarStatus.LONG`;去掉 import 里的 `ContractType`(第 6 行改为 `from app.enums import Category, CarStatus, ACTIVE_STATUSES`)。函数体:
```python
def create_car(session: Session, *, nickname: str, category: Category,
               brand: str, casting: str, description: str,
               team_id: Optional[int], image_path: Optional[str] = None,
               signed_status: CarStatus = CarStatus.LONG) -> Car:
    _check_unique_nickname(session, nickname)
    car = Car(nickname=nickname, category=category, brand=brand, casting=casting,
              description=description, image_path=image_path,
              status=CarStatus.UNSIGNED)
    if team_id is not None:
        team = session.get(Team, team_id)
        if team is None:
            raise CarValidationError("车队不存在")
        tsvc.check_can_assign(session, car=car, team=team)
        car.team_id = team_id
        car.status = signed_status            # 长期/短期合约
    session.add(car)
    session.commit()
    session.refresh(car)
    return car
```

- [ ] **Step 4: 改 `update_car`(82-117)**

```python
def update_car(session: Session, car_id: int, **fields) -> Car:
    car = session.get(Car, car_id)
    if car is None:
        raise CarValidationError("赛车不存在")
    if "nickname" in fields:
        _check_unique_nickname(session, fields["nickname"], exclude_id=car_id)
    new_team_id = fields.get("team_id", car.team_id)
    signed_status = fields.pop("signed_status", CarStatus.LONG)
    for k, v in fields.items():
        if k != "team_id":
            setattr(car, k, v)
    if new_team_id is None:
        car.team_id = None
        car.status = CarStatus.UNSIGNED
    else:
        team = session.get(Team, new_team_id)
        if team is None:
            raise CarValidationError("车队不存在")
        if car.status == CarStatus.RETIRED:
            # 退役车编辑:保持退役,仅允许换队(带品牌校验)
            if (team.type == tsvc.TeamType.FACTORY
                    and not tsvc.is_brandless(car.brand)
                    and car.brand != team.brand):
                raise tsvc.TeamValidationError(
                    f"厂商车队「{team.name}」只能加入品牌为「{team.brand}」或无品牌的赛车")
            car.team_id = new_team_id
        else:
            # 未签约/现役:加入或换队/改合约 → 落具体合约,校验名额
            tsvc.check_can_assign(session, car=car, team=team)
            car.team_id = new_team_id
            car.status = signed_status
    session.add(car)
    session.commit()
    session.refresh(car)
    return car
```

- [ ] **Step 5: 改路由 `app/routers/cars.py`**

第 13 行 import 去掉 `ContractType`:`from app.enums import Category, CarStatus`。
辅助:在文件顶部(`_teams` 上方)加映射函数:
```python
def _signed_status(contract: str) -> CarStatus:
    return CarStatus.SHORT if contract == "短期" else CarStatus.LONG
```
`create_car` 路由(42-54):把参数 `contract: str = Form("")` 保留,调用改为:
```python
        car = csvc.create_car(
            session, nickname=nickname, category=Category(category), brand=brand,
            casting=casting, description=description,
            team_id=int(team_id) if team_id else None,
            image_path=_save_image(image),
            signed_status=_signed_status(contract))
```
`edit_car` 路由(80-83):`fields` 里把 `contract=...` 换为:
```python
                  signed_status=_signed_status(contract))
```
(其余字段不变。)

- [ ] **Step 6: 改 `app/templates/car_form.html`(27-32)**

把「合同」选择块替换为(默认长期,值用中文,与 `_signed_status` 对应):
```html
    <label>合约(有车队时生效)</label>
    <select name="contract">
      <option value="长期" {{ "selected" if not car or car.status.value != "短期合约" else "" }}>长期</option>
      <option value="短期" {{ "selected" if car and car.status.value == "短期合约" else "" }}>短期</option>
    </select>
```

- [ ] **Step 7: 跑相关测试,确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cars_signing.py tests/test_status_machine.py -q`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add app/services/cars.py app/routers/cars.py app/templates/car_form.html tests/test_cars_signing.py
git commit -m "refactor(status): 创建/编辑赛车用签约状态,表单合约即状态"
```

---

## Task 5: 模板显示(状态下拉与标签)

**Files:**
- Modify: `app/templates/_car_rows.html:14`、`app/templates/car_detail.html:10`、`app/templates/market.html:27`

- [ ] **Step 1: `_car_rows.html` 状态下拉(第 14 行)**

```html
      {% for s in ["未签约","长期合约","短期合约","退役"] %}
```

- [ ] **Step 2: `car_detail.html`(第 10 行)**

去掉「合同」段,改显示状态:
```html
      <p><small>{{ car.casting }} · {{ car.brand }} · 车队:{{ team_name or "无车队" }} · {{ car.status.value }}</small></p>
```

- [ ] **Step 3: `market.html`(第 27 行)**

合约标签改用状态:
```html
      {% if r.car.status.is_active %}<span class="tag">{{ r.car.status.value }}</span>{% endif %}</span>
```

- [ ] **Step 4: 提交**

```bash
git add app/templates/_car_rows.html app/templates/car_detail.html app/templates/market.html
git commit -m "refactor(status): 模板状态下拉/标签同步 4 值"
```

---

## Task 6: 启动数据迁移 `'ACTIVE'→'LONG'`

**Files:**
- Modify: `app/db.py`(`init_db` 末尾追加迁移)

- [ ] **Step 1: 改 `init_db`**

在 `init_db` 中 `_backfill_after_migration(...)` 之后追加(原始 SQL,幂等):
```python
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("UPDATE car SET status='LONG' WHERE status='ACTIVE'"))
```
(`text` 已在 db.py 顶部导入;若未导入则用文件已有的 `from sqlalchemy import inspect, text`。)

- [ ] **Step 2: 提交**

```bash
git add app/db.py
git commit -m "refactor(status): 启动迁移 现役(ACTIVE)→长期合约(LONG)"
```

---

## Task 7: 更新现有测试 + 全套跑绿

把旧测试里的 `ContractType`、`CarStatus.ACTIVE`、`create_car(contract=...)` 全部改到新模型。

**Files:**
- Modify: `tests/test_market.py`、`tests/test_salary.py`,以及任何仍引用旧符号的测试。

- [ ] **Step 1: 先全跑,列出红项**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 多处 FAIL(ImportError `ContractType` / `status==ACTIVE` 断言)

- [ ] **Step 2: `tests/test_salary.py`**

- 删除 `from app.enums import ContractType`(第 4 行)与对应导入。
- `test_new_tables_and_contract`:去掉 `contract=ContractType.LONG` 与断言 `c.contract==...`;改为:
```python
    c = Car(nickname="x", category=Category.GT3, status=CarStatus.LONG)
    session.add(c); session.commit(); session.refresh(c)
    assert c.status == CarStatus.LONG
```
(顶部 `from app.enums import Category, CarStatus`。)

- [ ] **Step 3: `tests/test_market.py`**

- 顶部 import:去掉 `ContractType`,保留 `CarStatus`。
- `_seed`:`long_car` 用 `signed_status=CarStatus.LONG`,`short_car` 用 `signed_status=CarStatus.SHORT`(把 `contract=...` 改名)。
- `test_open_market_releases_short_keeps_long`:断言改为
```python
    assert session.get(Car, long_car.id).status == CarStatus.LONG
    assert session.get(Car, short_car.id).status == CarStatus.UNSIGNED
```
(删掉对 `.contract` 的断言)。
- `test_headroom_and_sign`:签回后断言 `status == CarStatus.SHORT`(`sign` 落短期);删 `.contract` 断言。
- 其它 `create_car(... contract=ContractType.X)` → `signed_status=CarStatus.X`;`status == CarStatus.ACTIVE` → `status.is_active`。

- [ ] **Step 4: 其它测试**

全跑后按报错逐个把残留的 `CarStatus.ACTIVE` 断言改为 `.is_active`、`ContractType` 引用删除。常见:`tests/test_pages.py`、`tests/test_team_points.py`、`tests/test_standings.py`(若有)。

- [ ] **Step 5: 全套跑绿**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS(全绿)

- [ ] **Step 6: 提交**

```bash
git add tests/
git commit -m "test(status): 测试更新到单一签约状态模型"
```

---

## Task 8: 文档与现库迁移验证

**Files:**
- Modify: `CLAUDE.md`(状态铁律一段)

- [ ] **Step 1: 改 `CLAUDE.md`**

把「赛车状态:未签约 / 现役 / 退役」一段改为 4 值,并说明「现役 = 长期合约 或 短期合约」;删掉对 `ContractType` 的隐含描述(若有)。专业赛仅限现役(长期/短期)。

- [ ] **Step 2: 验证现库迁移(只读 + 启动一次)**

Run:
```bash
.venv/Scripts/python.exe -c "from app import db; db.init_db(); from sqlmodel import Session, select; from app.models import Car; s=Session(db.get_engine()); print(sorted({c.status.value for c in s.exec(select(Car)).all()}))"
```
Expected: 输出里不含「现役」;现役车已变「长期合约」。

- [ ] **Step 3: 全套跑绿 + 提交**

```bash
.venv/Scripts/python.exe -m pytest -q
git add CLAUDE.md data/hotwheel.db
git commit -m "docs(status): CLAUDE.md 更新签约状态;迁移现库数据"
```

---

## 验证(端到端)

1. `.venv/Scripts/python.exe -m pytest -q` 全绿。
2. 启动服务(`start.bat` 或 uvicorn),`/database` 列表状态下拉显示 4 值;新建带车队的车可选长期/短期;退役→复出弹出/落具体合约。
3. `/market` 开盘后短期合约车被释放、长期留任。
4. 现库 `雷诺2024` 等原现役车显示「长期合约」。
