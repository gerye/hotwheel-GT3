# 计划一:地基 + 数据库页面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭好项目骨架与 SQLite 数据层(Car/Team/Season 模型 + 约束校验),并实现统一数据库页面(列表/全局搜索/新增/编辑)与赛车、车队、赛季的实时生成个人页。

**Architecture:** FastAPI 单进程应用,SQLModel 映射 SQLite,Jinja2 服务端渲染 + HTMX 局部交互。业务规则集中在 `app/services/`,路由只做请求编排。MMR/积分字段在本计划仅作为默认值存在,具体结算逻辑在计划二、三实现。

**Tech Stack:** Python 3.11+, FastAPI, SQLModel, Uvicorn, Jinja2, HTMX, pytest, FastAPI TestClient, Pillow(图片保存)。

---

## 文件结构(本计划创建/涉及)

```
pyproject.toml              # 依赖与项目配置
app/
  __init__.py
  config.py                 # 路径/常量(DB 路径、图片目录)
  db.py                     # engine、get_session、init_db
  enums.py                  # Category/TeamType/ProLevel/RaceFormat/SeasonStatus...
  models.py                 # Car/Team/Season/CarSeasonMMR(本计划只建表)
  services/
    __init__.py
    teams.py                # 车队约束校验 + 创建/更新
    cars.py                 # 赛车创建/更新(含车队约束联动)
    search.py               # 全字段搜索
    seasons.py              # 赛季创建/结束/开启
  routers/
    __init__.py
    pages.py                # 统一数据库页 + 个人页
    cars.py                 # 赛车增改/搜索 HTMX 端点
    teams.py                # 车队增改 HTMX 端点
    seasons.py              # 赛季页与操作
  main.py                   # 装配 app、挂载 static、模板、路由
  templates/
    base.html
    database.html
    _car_rows.html
    _team_rows.html
    car_detail.html
    car_form.html
    team_detail.html
    team_form.html
    seasons.html
    season_detail.html
  static/
    style.css
    htmx.min.js
tests/
  conftest.py
  test_models.py
  test_teams_service.py
  test_cars_service.py
  test_search_service.py
  test_seasons_service.py
  test_pages.py
  test_cars_routes.py
  test_teams_routes.py
data/                       # 运行期生成(gitignore):hotwheel.db, images/
```

---

## Task 1: 项目骨架与依赖

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `app/__init__.py`
- Create: `app/config.py`

- [ ] **Step 1: 写 pyproject.toml**

```toml
[project]
name = "hotwheel-gt3"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "sqlmodel>=0.0.16",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
    "pillow>=10.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]

[tool.pytest.ini_options]
addopts = "-q"
testpaths = ["tests"]
```

- [ ] **Step 2: 写 .gitignore**

```gitignore
__pycache__/
*.pyc
.venv/
data/
.pytest_cache/
```

- [ ] **Step 3: 写 app/__init__.py(空文件)**

```python
```

- [ ] **Step 4: 写 app/config.py**

```python
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "hotwheel.db"

NUM_LANES = 4          # 跑道数
INITIAL_MMR = 1500.0   # 初始 MMR
MAX_CARS_PER_CATEGORY = 2  # 每车队每类别最多车数


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    IMAGES_DIR.mkdir(exist_ok=True)
```

- [ ] **Step 5: 安装依赖并提交**

Run: `python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`
Expected: 安装成功,无报错。

```bash
git add pyproject.toml .gitignore app/__init__.py app/config.py
git commit -m "chore: project skeleton and config"
```

---

## Task 2: 枚举定义

**Files:**
- Create: `app/enums.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_models.py
from app.enums import Category, TeamType, ProLevel, RaceFormat, SeasonStatus


def test_category_values():
    assert Category.F1.value == "F1"
    assert Category.GT3.value == "GT3"
    assert Category.ROAD.value == "公路车"
    assert [c.value for c in Category] == ["F1", "GT3", "公路车"]


def test_team_and_level_enums():
    assert TeamType.FACTORY.value == "厂商车队"
    assert TeamType.INDEPENDENT.value == "独立车队"
    assert ProLevel.PRO.value == "专业"
    assert ProLevel.EXHIBITION.value == "表演"
    assert RaceFormat.SOLO.value == "单人锦标赛"
    assert RaceFormat.TEAM.value == "车队锦标赛"
    assert SeasonStatus.ACTIVE.value == "进行中"
    assert SeasonStatus.FINISHED.value == "已结束"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_models.py::test_category_values -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'app.enums'`

- [ ] **Step 3: 写 app/enums.py**

```python
from enum import Enum


class Category(str, Enum):
    F1 = "F1"
    GT3 = "GT3"
    ROAD = "公路车"


class TeamType(str, Enum):
    FACTORY = "厂商车队"
    INDEPENDENT = "独立车队"


class ProLevel(str, Enum):
    PRO = "专业"
    EXHIBITION = "表演"


class RaceFormat(str, Enum):
    SOLO = "单人锦标赛"
    TEAM = "车队锦标赛"


class RaceStatus(str, Enum):
    IN_PROGRESS = "进行中"
    FINISHED = "已结束"


class SeasonStatus(str, Enum):
    ACTIVE = "进行中"
    FINISHED = "已结束"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/enums.py tests/test_models.py
git commit -m "feat: domain enums"
```

---

## Task 3: 数据模型与数据库初始化

**Files:**
- Create: `app/models.py`
- Create: `app/db.py`
- Test: `tests/conftest.py`, `tests/test_models.py`(追加)

- [ ] **Step 1: 写 db.py**

```python
# app/db.py
from collections.abc import Iterator
from sqlmodel import Session, SQLModel, create_engine
from app import config

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        config.ensure_dirs()
        _engine = create_engine(
            f"sqlite:///{config.DB_PATH}",
            connect_args={"check_same_thread": False},
        )
    return _engine


def set_engine(engine) -> None:
    """测试用:注入内存引擎。"""
    global _engine
    _engine = engine


def init_db() -> None:
    import app.models  # noqa: F401  确保模型已注册
    SQLModel.metadata.create_all(get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
```

- [ ] **Step 2: 写 models.py**

```python
# app/models.py
from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel
from app.enums import Category, TeamType, SeasonStatus


class Team(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    type: TeamType
    brand: Optional[str] = None          # 仅厂商车队
    name: str = Field(index=True)        # 显示名(厂商=品牌+车队;独立=用户名称)


class Car(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nickname: str = Field(index=True, unique=True)
    image_path: Optional[str] = None
    casting: str = ""
    brand: str = ""
    category: Category
    description: str = ""
    team_id: Optional[int] = Field(default=None, foreign_key="team.id")
    season_mmr: float = 1500.0
    historical_mmr: float = 1500.0


class Season(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    status: SeasonStatus = SeasonStatus.ACTIVE
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None


class CarSeasonMMR(SQLModel, table=True):
    """赛季结束时为每辆车保存的 MMR 快照。"""
    id: Optional[int] = Field(default=None, primary_key=True)
    season_id: int = Field(foreign_key="season.id")
    car_id: int = Field(foreign_key="car.id")
    mmr: float
```

- [ ] **Step 3: 写 conftest.py(内存数据库 fixture)**

```python
# tests/conftest.py
import pytest
from sqlmodel import SQLModel, Session, create_engine
from sqlmodel.pool import StaticPool
from app import db


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import app.models  # noqa: F401
    SQLModel.metadata.create_all(eng)
    db.set_engine(eng)
    yield eng
    db.set_engine(None)


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s
```

- [ ] **Step 4: 追加模型建表测试**

```python
# tests/test_models.py 追加
from sqlmodel import select
from app.models import Car, Team
from app.enums import Category, TeamType


def test_can_insert_and_query_car(session):
    team = Team(type=TeamType.INDEPENDENT, name="车库突击队")
    session.add(team)
    session.commit()
    car = Car(nickname="红色闪电", category=Category.GT3, team_id=team.id)
    session.add(car)
    session.commit()
    got = session.exec(select(Car).where(Car.nickname == "红色闪电")).one()
    assert got.season_mmr == 1500.0
    assert got.team_id == team.id
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_models.py -v`
Expected: PASS(包含 Task 2 的枚举测试)

- [ ] **Step 6: 提交**

```bash
git add app/db.py app/models.py tests/conftest.py tests/test_models.py
git commit -m "feat: data models and db init"
```

---

## Task 4: 车队约束校验(纯函数)

**Files:**
- Create: `app/services/__init__.py`(空)
- Create: `app/services/teams.py`
- Test: `tests/test_teams_service.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_teams_service.py
import pytest
from app.models import Team, Car
from app.enums import TeamType, Category
from app.services import teams as svc


def _factory(session, brand="法拉利"):
    t = Team(type=TeamType.FACTORY, brand=brand, name=f"{brand}车队")
    session.add(t); session.commit(); session.refresh(t)
    return t


def test_factory_team_name_is_brand_plus_suffix(session):
    t = svc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    assert t.name == "法拉利车队"


def test_independent_team_keeps_given_name(session):
    t = svc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="车库突击队")
    assert t.name == "车库突击队"


def test_factory_requires_brand(session):
    with pytest.raises(svc.TeamValidationError):
        svc.create_team(session, type=TeamType.FACTORY, brand=None, name=None)


def test_independent_requires_name(session):
    with pytest.raises(svc.TeamValidationError):
        svc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="")


def test_assign_car_brand_mismatch_to_factory_rejected(session):
    t = _factory(session, "法拉利")
    car = Car(nickname="蓝鲨", category=Category.GT3, brand="保时捷")
    session.add(car); session.commit(); session.refresh(car)
    with pytest.raises(svc.TeamValidationError):
        svc.check_can_assign(session, car=car, team=t)


def test_assign_car_brand_match_to_factory_ok(session):
    t = _factory(session, "法拉利")
    car = Car(nickname="红色闪电", category=Category.GT3, brand="法拉利")
    session.add(car); session.commit(); session.refresh(car)
    svc.check_can_assign(session, car=car, team=t)  # 不抛异常


def test_category_capacity_enforced(session):
    t = _factory(session, "法拉利")
    for i in range(2):
        c = Car(nickname=f"红{i}", category=Category.GT3, brand="法拉利", team_id=t.id)
        session.add(c)
    session.commit()
    third = Car(nickname="红3", category=Category.GT3, brand="法拉利")
    session.add(third); session.commit(); session.refresh(third)
    with pytest.raises(svc.TeamValidationError):
        svc.check_can_assign(session, car=third, team=t)


def test_capacity_counts_per_category(session):
    t = _factory(session, "法拉利")
    for i in range(2):
        session.add(Car(nickname=f"g{i}", category=Category.GT3, brand="法拉利", team_id=t.id))
    session.commit()
    f1car = Car(nickname="f1", category=Category.F1, brand="法拉利")
    session.add(f1car); session.commit(); session.refresh(f1car)
    svc.check_can_assign(session, car=f1car, team=t)  # 不同类别不超额,放行
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_teams_service.py -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'app.services.teams'`

- [ ] **Step 3: 写 services/teams.py**

```python
# app/services/teams.py
from typing import Optional
from sqlmodel import Session, select
from app.models import Team, Car
from app.enums import TeamType, Category
from app.config import MAX_CARS_PER_CATEGORY


class TeamValidationError(Exception):
    pass


def create_team(session: Session, *, type: TeamType,
                brand: Optional[str], name: Optional[str]) -> Team:
    if type == TeamType.FACTORY:
        if not brand:
            raise TeamValidationError("厂商车队必须填写品牌")
        team = Team(type=type, brand=brand, name=f"{brand}车队")
    else:
        if not name:
            raise TeamValidationError("独立车队必须填写名称")
        team = Team(type=type, brand=None, name=name)
    session.add(team)
    session.commit()
    session.refresh(team)
    return team


def _category_count(session: Session, team_id: int, category: Category,
                    exclude_car_id: Optional[int]) -> int:
    rows = session.exec(
        select(Car).where(Car.team_id == team_id, Car.category == category)
    ).all()
    return len([c for c in rows if c.id != exclude_car_id])


def check_can_assign(session: Session, *, car: Car, team: Team) -> None:
    """把 car 放进 team 前的校验;不通过抛 TeamValidationError。"""
    if team.type == TeamType.FACTORY and car.brand != team.brand:
        raise TeamValidationError(
            f"厂商车队「{team.name}」只能加入品牌为「{team.brand}」的赛车")
    count = _category_count(session, team.id, car.category, exclude_car_id=car.id)
    if count >= MAX_CARS_PER_CATEGORY:
        raise TeamValidationError(
            f"车队「{team.name}」在 {car.category.value} 类别已满 "
            f"({MAX_CARS_PER_CATEGORY} 辆)")
```

- [ ] **Step 4: 写 services/__init__.py(空)**

```python
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_teams_service.py -v`
Expected: PASS(8 个测试全过)

- [ ] **Step 6: 提交**

```bash
git add app/services/__init__.py app/services/teams.py tests/test_teams_service.py
git commit -m "feat: team constraint validation service"
```

---

## Task 5: 赛车创建/更新服务(含车队联动校验)

**Files:**
- Create: `app/services/cars.py`
- Test: `tests/test_cars_service.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cars_service.py
import pytest
from app.models import Car
from app.enums import Category, TeamType
from app.services import cars as svc
from app.services import teams as tsvc


def test_create_car_minimal(session):
    car = svc.create_car(session, nickname="红色闪电", category=Category.GT3,
                         brand="法拉利", casting="Custom01", description="", team_id=None)
    assert car.id is not None
    assert car.season_mmr == 1500.0


def test_duplicate_nickname_rejected(session):
    svc.create_car(session, nickname="红色闪电", category=Category.GT3,
                   brand="法拉利", casting="", description="", team_id=None)
    with pytest.raises(svc.CarValidationError):
        svc.create_car(session, nickname="红色闪电", category=Category.F1,
                       brand="法拉利", casting="", description="", team_id=None)


def test_create_car_into_factory_brand_mismatch_rejected(session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    with pytest.raises(tsvc.TeamValidationError):
        svc.create_car(session, nickname="蓝鲨", category=Category.GT3,
                       brand="保时捷", casting="", description="", team_id=t.id)


def test_change_car_team_runs_constraint(session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    car = svc.create_car(session, nickname="蓝鲨", category=Category.GT3,
                         brand="保时捷", casting="", description="", team_id=None)
    with pytest.raises(tsvc.TeamValidationError):
        svc.update_car(session, car.id, team_id=t.id)


def test_change_car_team_to_none_ok(session):
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="独立队")
    car = svc.create_car(session, nickname="蓝鲨", category=Category.GT3,
                         brand="保时捷", casting="", description="", team_id=t.id)
    updated = svc.update_car(session, car.id, team_id=None)
    assert updated.team_id is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_cars_service.py -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'app.services.cars'`

- [ ] **Step 3: 写 services/cars.py**

```python
# app/services/cars.py
from typing import Optional
from sqlmodel import Session, select
from app.models import Car, Team
from app.enums import Category
from app.services import teams as tsvc


class CarValidationError(Exception):
    pass


def _check_unique_nickname(session: Session, nickname: str,
                           exclude_id: Optional[int] = None) -> None:
    existing = session.exec(select(Car).where(Car.nickname == nickname)).first()
    if existing and existing.id != exclude_id:
        raise CarValidationError(f"昵称「{nickname}」已存在")


def create_car(session: Session, *, nickname: str, category: Category,
               brand: str, casting: str, description: str,
               team_id: Optional[int], image_path: Optional[str] = None) -> Car:
    _check_unique_nickname(session, nickname)
    car = Car(nickname=nickname, category=category, brand=brand, casting=casting,
              description=description, image_path=image_path)
    if team_id is not None:
        team = session.get(Team, team_id)
        if team is None:
            raise CarValidationError("车队不存在")
        tsvc.check_can_assign(session, car=car, team=team)
        car.team_id = team_id
    session.add(car)
    session.commit()
    session.refresh(car)
    return car


def update_car(session: Session, car_id: int, **fields) -> Car:
    car = session.get(Car, car_id)
    if car is None:
        raise CarValidationError("赛车不存在")
    if "nickname" in fields:
        _check_unique_nickname(session, fields["nickname"], exclude_id=car_id)
    new_team_id = fields.get("team_id", car.team_id)
    # 先把字段套到对象上(用于品牌/类别变更联动校验),再校验车队
    for k, v in fields.items():
        if k != "team_id":
            setattr(car, k, v)
    if new_team_id is not None:
        team = session.get(Team, new_team_id)
        if team is None:
            raise CarValidationError("车队不存在")
        tsvc.check_can_assign(session, car=car, team=team)
    car.team_id = new_team_id
    session.add(car)
    session.commit()
    session.refresh(car)
    return car
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_cars_service.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/cars.py tests/test_cars_service.py
git commit -m "feat: car create/update service with team constraints"
```

---

## Task 6: 全字段搜索服务

**Files:**
- Create: `app/services/search.py`
- Test: `tests/test_search_service.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_search_service.py
from app.enums import Category, TeamType
from app.services import cars as csvc, teams as tsvc, search as ssvc


def _seed(session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    csvc.create_car(session, nickname="红色闪电", category=Category.GT3,
                    brand="法拉利", casting="Custom01", description="弯道稳定", team_id=t.id)
    csvc.create_car(session, nickname="蓝鲨", category=Category.GT3,
                    brand="保时捷", casting="Aero99", description="直线快", team_id=None)


def test_search_by_nickname(session):
    _seed(session)
    res = ssvc.search_cars(session, "红色")
    assert [c.nickname for c in res] == ["红色闪电"]


def test_search_by_brand(session):
    _seed(session)
    res = ssvc.search_cars(session, "保时捷")
    assert [c.nickname for c in res] == ["蓝鲨"]


def test_search_by_description(session):
    _seed(session)
    res = ssvc.search_cars(session, "弯道")
    assert [c.nickname for c in res] == ["红色闪电"]


def test_search_by_casting(session):
    _seed(session)
    res = ssvc.search_cars(session, "Aero")
    assert [c.nickname for c in res] == ["蓝鲨"]


def test_empty_query_returns_all(session):
    _seed(session)
    assert len(ssvc.search_cars(session, "")) == 2


def test_filter_by_category(session):
    _seed(session)
    res = ssvc.search_cars(session, "", category=Category.GT3)
    assert len(res) == 2
    res2 = ssvc.search_cars(session, "", category=Category.F1)
    assert res2 == []


def test_search_teams_by_name_and_brand(session):
    _seed(session)
    assert len(ssvc.search_teams(session, "法拉利")) == 1
    assert len(ssvc.search_teams(session, "")) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_search_service.py -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'app.services.search'`

- [ ] **Step 3: 写 services/search.py**

```python
# app/services/search.py
from typing import Optional
from sqlmodel import Session, select, or_
from app.models import Car, Team
from app.enums import Category


def search_cars(session: Session, query: str,
                category: Optional[Category] = None) -> list[Car]:
    stmt = select(Car)
    q = (query or "").strip()
    if q:
        like = f"%{q}%"
        # 把车队名也纳入搜索:先查出匹配车队的 id
        team_ids = [t.id for t in session.exec(
            select(Team).where(Team.name.like(like))).all()]
        conditions = [
            Car.nickname.like(like),
            Car.brand.like(like),
            Car.casting.like(like),
            Car.description.like(like),
        ]
        if team_ids:
            conditions.append(Car.team_id.in_(team_ids))
        stmt = stmt.where(or_(*conditions))
    if category is not None:
        stmt = stmt.where(Car.category == category)
    return list(session.exec(stmt.order_by(Car.nickname)).all())


def search_teams(session: Session, query: str) -> list[Team]:
    stmt = select(Team)
    q = (query or "").strip()
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Team.name.like(like), Team.brand.like(like)))
    return list(session.exec(stmt.order_by(Team.name)).all())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_search_service.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/search.py tests/test_search_service.py
git commit -m "feat: full-field search service"
```

---

## Task 7: 赛季服务(创建/结束/开启)

**Files:**
- Create: `app/services/seasons.py`
- Test: `tests/test_seasons_service.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_seasons_service.py
import pytest
from app.enums import SeasonStatus
from app.services import seasons as svc


def test_first_season_created_active(session):
    s = svc.start_season(session, name="2026 S1")
    assert s.status == SeasonStatus.ACTIVE
    assert svc.get_active_season(session).id == s.id


def test_cannot_start_second_active_season(session):
    svc.start_season(session, name="2026 S1")
    with pytest.raises(svc.SeasonError):
        svc.start_season(session, name="2026 S2")


def test_end_then_start_next(session):
    s1 = svc.start_season(session, name="2026 S1")
    svc.end_season(session, s1.id)
    assert svc.get_active_season(session) is None
    s2 = svc.start_season(session, name="2026 S2")
    assert s2.status == SeasonStatus.ACTIVE


def test_end_season_sets_ended_at(session):
    s1 = svc.start_season(session, name="2026 S1")
    ended = svc.end_season(session, s1.id)
    assert ended.status == SeasonStatus.FINISHED
    assert ended.ended_at is not None
```

> 备注:`end_season` 在本计划只负责标记赛季结束。MMR 快照与车队积分清零的钩子在计划三实现并在此调用。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_seasons_service.py -v`
Expected: FAIL,`ModuleNotFoundError`

- [ ] **Step 3: 写 services/seasons.py**

```python
# app/services/seasons.py
from datetime import datetime
from typing import Optional
from sqlmodel import Session, select
from app.models import Season
from app.enums import SeasonStatus


class SeasonError(Exception):
    pass


def get_active_season(session: Session) -> Optional[Season]:
    return session.exec(
        select(Season).where(Season.status == SeasonStatus.ACTIVE)
    ).first()


def start_season(session: Session, *, name: str) -> Season:
    if get_active_season(session) is not None:
        raise SeasonError("已有进行中的赛季,请先结束当前赛季")
    s = Season(name=name, status=SeasonStatus.ACTIVE)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def end_season(session: Session, season_id: int) -> Season:
    s = session.get(Season, season_id)
    if s is None:
        raise SeasonError("赛季不存在")
    if s.status == SeasonStatus.FINISHED:
        raise SeasonError("赛季已结束")
    # 计划三:在此处插入 MMR 快照与车队积分清零钩子
    s.status = SeasonStatus.FINISHED
    s.ended_at = datetime.utcnow()
    session.add(s)
    session.commit()
    session.refresh(s)
    return s
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_seasons_service.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/seasons.py tests/test_seasons_service.py
git commit -m "feat: season lifecycle service"
```

---

## Task 8: FastAPI 应用装配 + 模板基座

**Files:**
- Create: `app/main.py`
- Create: `app/routers/__init__.py`(空)
- Create: `app/templates/base.html`
- Create: `app/static/style.css`
- Create: `app/static/htmx.min.js`(从 CDN 下载放入)
- Test: `tests/test_pages.py`

- [ ] **Step 1: 写失败测试(健康检查首页)**

```python
# tests/test_pages.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_home_redirects_to_database(engine):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "/database" in r.headers["location"]
```

> 注意:`tests/conftest.py` 的 `engine` fixture 已用内存库覆盖 `db.set_engine`,`TestClient` 走同一引擎。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_pages.py -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: 下载 htmx**

Run: `curl -L https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js -o app/static/htmx.min.js`
Expected: 文件存在且非空。

- [ ] **Step 4: 写 base.html**

```html
<!-- app/templates/base.html -->
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}风火轮 GT3{% endblock %}</title>
  <link rel="stylesheet" href="/static/style.css">
  <script src="/static/htmx.min.js"></script>
</head>
<body>
  <nav class="topnav">
    <a href="/database">数据库</a>
    <a href="/races">赛事</a>
    <a href="/standings">荣誉榜</a>
    <a href="/seasons">赛季</a>
  </nav>
  <main>{% block content %}{% endblock %}</main>
</body>
</html>
```

- [ ] **Step 5: 写 style.css(响应式基线)**

```css
/* app/static/style.css */
* { box-sizing: border-box; }
body { font-family: system-ui, sans-serif; margin: 0; color: #1a1a1a; background: #fafafa; }
.topnav { display: flex; gap: 16px; padding: 12px 16px; background: #fff; border-bottom: 1px solid #eee; position: sticky; top: 0; }
.topnav a { text-decoration: none; color: #333; font-size: 15px; }
main { max-width: 900px; margin: 0 auto; padding: 16px; }
.row { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-top: 1px solid #eee; }
.row img, .thumb { width: 48px; height: 36px; object-fit: cover; border-radius: 6px; background: #eee; }
.tag { font-size: 11px; padding: 3px 8px; border-radius: 6px; background: #f3eccf; color: #855; }
.btn { display: inline-block; padding: 6px 12px; border: 1px solid #ccc; border-radius: 6px; background: #fff; cursor: pointer; font-size: 14px; text-decoration: none; color: #222; }
.card { background: #fff; border: 1px solid #eee; border-radius: 12px; padding: 16px; margin-bottom: 16px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
.stat { background: #f6f6f6; border-radius: 8px; padding: 12px; }
.stat .label { font-size: 12px; color: #777; }
.stat .value { font-size: 22px; }
input, select, textarea { font: inherit; padding: 8px; border: 1px solid #ccc; border-radius: 6px; width: 100%; }
label { display: block; margin: 10px 0 4px; font-size: 13px; color: #555; }
.error { color: #b00; font-size: 13px; margin: 6px 0; }
@media (max-width: 600px) { main { padding: 10px; } .grid { grid-template-columns: 1fr 1fr; } }
```

- [ ] **Step 6: 写 routers/__init__.py(空)**

```python
```

- [ ] **Step 7: 写 main.py**

```python
# app/main.py
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from app import config, db

app = FastAPI(title="风火轮 GT3")


@app.on_event("startup")
def _startup() -> None:
    config.ensure_dirs()
    db.init_db()


app.mount("/static", StaticFiles(directory=config.BASE_DIR / "app" / "static"),
          name="static")


@app.get("/")
def home() -> RedirectResponse:
    return RedirectResponse(url="/database")


# 路由在后续任务中注册
from app.routers import pages, cars, teams, seasons  # noqa: E402
app.include_router(pages.router)
app.include_router(cars.router)
app.include_router(teams.router)
app.include_router(seasons.router)
```

> 实现顺序提醒:Task 8 先建空的 `pages/cars/teams/seasons` router(各含 `router = APIRouter()`),以便 import 不报错;Task 9-12 再往里填端点。下面 Step 8 建占位。

- [ ] **Step 8: 建四个占位 router**

```python
# app/routers/pages.py
from fastapi import APIRouter
router = APIRouter()
```
```python
# app/routers/cars.py
from fastapi import APIRouter
router = APIRouter()
```
```python
# app/routers/teams.py
from fastapi import APIRouter
router = APIRouter()
```
```python
# app/routers/seasons.py
from fastapi import APIRouter
router = APIRouter()
```

- [ ] **Step 9: 运行测试确认通过**

Run: `pytest tests/test_pages.py -v`
Expected: PASS

- [ ] **Step 10: 提交**

```bash
git add app/main.py app/routers/ app/templates/base.html app/static/
git commit -m "feat: app assembly, base template, static assets"
```

---

## Task 9: 统一数据库页(列表 + 标签 + 全局搜索)

**Files:**
- Modify: `app/routers/pages.py`
- Create: `app/templates/database.html`, `app/templates/_car_rows.html`, `app/templates/_team_rows.html`
- Test: `tests/test_pages.py`(追加)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pages.py 追加
from app.enums import Category, TeamType
from app.services import cars as csvc, teams as tsvc


def test_database_lists_cars(engine, session):
    csvc.create_car(session, nickname="红色闪电", category=Category.GT3,
                    brand="法拉利", casting="C01", description="", team_id=None)
    r = client.get("/database")
    assert r.status_code == 200
    assert "红色闪电" in r.text


def test_database_search_filters(engine, session):
    csvc.create_car(session, nickname="红色闪电", category=Category.GT3,
                    brand="法拉利", casting="C01", description="", team_id=None)
    csvc.create_car(session, nickname="蓝鲨", category=Category.GT3,
                    brand="保时捷", casting="A99", description="", team_id=None)
    r = client.get("/database/cars?q=保时捷")
    assert "蓝鲨" in r.text and "红色闪电" not in r.text


def test_database_teams_tab(engine, session):
    tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    r = client.get("/database/teams")
    assert "法拉利车队" in r.text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_pages.py -k database -v`
Expected: FAIL(404 / 模板缺失)

- [ ] **Step 3: 写 _car_rows.html**

```html
<!-- app/templates/_car_rows.html -->
{% for car in cars %}
<a class="row" href="/cars/{{ car.id }}">
  {% if car.image_path %}<img src="/static/uploads/{{ car.image_path }}">{% else %}<span class="thumb"></span>{% endif %}
  <span style="flex:1">
    <strong>{{ car.nickname }}</strong><br>
    <small>{{ car.casting }} · {{ car.brand }} · {{ team_names.get(car.team_id, "无车队") }}</small>
  </span>
  <span class="tag">{{ car.category.value }}</span>
  <span><small>MMR {{ car.season_mmr | round | int }}</small></span>
</a>
{% else %}
<p>暂无赛车</p>
{% endfor %}
```

- [ ] **Step 4: 写 _team_rows.html**

```html
<!-- app/templates/_team_rows.html -->
{% for team in teams %}
<a class="row" href="/teams/{{ team.id }}">
  <span style="flex:1">
    <strong>{{ team.name }}</strong><br>
    <small>{{ team.type.value }}{% if team.brand %} · {{ team.brand }}{% endif %} · {{ counts.get(team.id, 0) }} 辆车</small>
  </span>
  <span class="tag">{{ "厂商" if team.type.value == "厂商车队" else "独立" }}</span>
</a>
{% else %}
<p>暂无车队</p>
{% endfor %}
```

- [ ] **Step 5: 写 database.html**

```html
<!-- app/templates/database.html -->
{% extends "base.html" %}
{% block content %}
<div style="display:flex;justify-content:space-between;align-items:center">
  <div>
    <a class="btn" href="/database">赛车</a>
    <a class="btn" href="/database/teams">车队</a>
  </div>
  <div>
    <a class="btn" href="/cars/new">+ 新增赛车</a>
    <a class="btn" href="/teams/new">+ 新增车队</a>
  </div>
</div>
<div style="margin:12px 0">
  <input type="search" name="q" placeholder="搜索所有字段…"
         hx-get="/database/cars" hx-trigger="keyup changed delay:300ms"
         hx-target="#list" hx-include="[name='category']">
  <select name="category" hx-get="/database/cars" hx-target="#list" hx-include="[name='q']" style="margin-top:8px">
    <option value="">全部类别</option>
    <option value="F1">F1</option>
    <option value="GT3">GT3</option>
    <option value="公路车">公路车</option>
  </select>
</div>
<div id="list" class="card">
  {% include "_car_rows.html" %}
</div>
{% endblock %}
```

- [ ] **Step 6: 写 pages.py 路由**

```python
# app/routers/pages.py
from typing import Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from app import config
from app.db import get_session
from app.models import Team
from app.enums import Category
from app.services import search as ssvc

router = APIRouter()
templates = Jinja2Templates(directory=config.BASE_DIR / "app" / "templates")


def _team_names(session: Session) -> dict[int, str]:
    return {t.id: t.name for t in session.exec(select(Team)).all()}


def _team_car_counts(session: Session) -> dict[int, int]:
    from app.models import Car
    counts: dict[int, int] = {}
    for c in session.exec(select(Car)).all():
        if c.team_id is not None:
            counts[c.team_id] = counts.get(c.team_id, 0) + 1
    return counts


@router.get("/database", response_class=HTMLResponse)
def database(request: Request, session: Session = Depends(get_session)):
    cars = ssvc.search_cars(session, "")
    return templates.TemplateResponse("database.html", {
        "request": request, "cars": cars, "team_names": _team_names(session),
    })


@router.get("/database/cars", response_class=HTMLResponse)
def database_cars(request: Request, q: str = "", category: str = "",
                  session: Session = Depends(get_session)):
    cat = Category(category) if category else None
    cars = ssvc.search_cars(session, q, category=cat)
    return templates.TemplateResponse("_car_rows.html", {
        "request": request, "cars": cars, "team_names": _team_names(session),
    })


@router.get("/database/teams", response_class=HTMLResponse)
def database_teams(request: Request, q: str = "",
                   session: Session = Depends(get_session)):
    teams = ssvc.search_teams(session, q)
    return templates.TemplateResponse("database.html", {
        "request": request, "cars": [], "teams": teams,
        "team_names": _team_names(session), "counts": _team_car_counts(session),
        "show_teams": True,
    })
```

> 说明:`/database/teams` 复用 `database.html` 但需要展示车队列表。为简洁,改 `database.html` 的 `#list` 区块支持两种数据(下一步)。

- [ ] **Step 7: 调整 database.html 的列表区块以支持车队标签页**

把 Step 5 中 `#list` 区块替换为:

```html
<div id="list" class="card">
  {% if show_teams %}
    {% include "_team_rows.html" %}
  {% else %}
    {% include "_car_rows.html" %}
  {% endif %}
</div>
```

- [ ] **Step 8: 运行测试确认通过**

Run: `pytest tests/test_pages.py -k database -v`
Expected: PASS

- [ ] **Step 9: 手动冒烟**

Run: `uvicorn app.main:app --port 8000` 然后浏览器开 `http://localhost:8000/database`
Expected: 看到赛车/车队标签、搜索框、空列表或已建数据。

- [ ] **Step 10: 提交**

```bash
git add app/routers/pages.py app/templates/database.html app/templates/_car_rows.html app/templates/_team_rows.html tests/test_pages.py
git commit -m "feat: unified database page with search"
```

---

## Task 10: 赛车新增/编辑表单 + 图片上传

**Files:**
- Modify: `app/routers/cars.py`
- Create: `app/templates/car_form.html`, `app/templates/car_detail.html`
- Modify: `app/main.py`(挂载上传目录到 /static/uploads)
- Test: `tests/test_cars_routes.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cars_routes.py
from fastapi.testclient import TestClient
from app.main import app
from app.enums import Category, TeamType
from app.services import teams as tsvc
from sqlmodel import select
from app.models import Car

client = TestClient(app)


def test_create_car_via_form(engine, session):
    r = client.post("/cars", data={
        "nickname": "红色闪电", "category": "GT3", "brand": "法拉利",
        "casting": "C01", "description": "稳", "team_id": "",
    }, follow_redirects=False)
    assert r.status_code in (302, 303)
    got = session.exec(select(Car).where(Car.nickname == "红色闪电")).one()
    assert got.brand == "法拉利"


def test_create_car_duplicate_shows_error(engine, session):
    client.post("/cars", data={"nickname": "红色闪电", "category": "GT3",
                "brand": "法拉利", "casting": "", "description": "", "team_id": ""})
    r = client.post("/cars", data={"nickname": "红色闪电", "category": "F1",
                "brand": "法拉利", "casting": "", "description": "", "team_id": ""})
    assert r.status_code == 200
    assert "已存在" in r.text


def test_create_car_factory_mismatch_shows_error(engine, session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    r = client.post("/cars", data={"nickname": "蓝鲨", "category": "GT3",
                "brand": "保时捷", "casting": "", "description": "", "team_id": str(t.id)})
    assert r.status_code == 200
    assert "品牌" in r.text


def test_edit_car(engine, session):
    client.post("/cars", data={"nickname": "红色闪电", "category": "GT3",
                "brand": "法拉利", "casting": "", "description": "", "team_id": ""})
    car = session.exec(select(Car)).one()
    r = client.post(f"/cars/{car.id}/edit", data={"nickname": "红色闪电2",
                "category": "GT3", "brand": "法拉利", "casting": "", "description": "改",
                "team_id": ""}, follow_redirects=False)
    assert r.status_code in (302, 303)
    session.refresh(car)
    assert car.nickname == "红色闪电2"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_cars_routes.py -v`
Expected: FAIL(404)

- [ ] **Step 3: main.py 挂载上传目录**

在 `app/main.py` 的 static 挂载之后追加:

```python
app.mount("/static/uploads", StaticFiles(directory=config.IMAGES_DIR),
          name="uploads")
```

并确保 `config.ensure_dirs()` 在挂载前已创建目录(在模块顶层调用一次):

```python
config.ensure_dirs()
```

- [ ] **Step 4: 写 car_form.html**

```html
<!-- app/templates/car_form.html -->
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h2>{{ "编辑赛车" if car else "新增赛车" }}</h2>
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
  <form method="post" action="{{ action }}" enctype="multipart/form-data">
    <label>昵称(唯一)</label>
    <input name="nickname" value="{{ car.nickname if car else "" }}" required>
    <label>类别</label>
    <select name="category">
      {% for c in ["F1","GT3","公路车"] %}
      <option value="{{ c }}" {{ "selected" if car and car.category.value==c else "" }}>{{ c }}</option>
      {% endfor %}
    </select>
    <label>品牌</label>
    <input name="brand" value="{{ car.brand if car else "" }}">
    <label>铸模</label>
    <input name="casting" value="{{ car.casting if car else "" }}">
    <label>所属车队</label>
    <select name="team_id">
      <option value="">无车队</option>
      {% for t in teams %}
      <option value="{{ t.id }}" {{ "selected" if car and car.team_id==t.id else "" }}>{{ t.name }}</option>
      {% endfor %}
    </select>
    <label>叙述</label>
    <textarea name="description" rows="3">{{ car.description if car else "" }}</textarea>
    <label>图片</label>
    <input type="file" name="image" accept="image/*">
    <div style="margin-top:12px"><button class="btn" type="submit">保存</button></div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 5: 写 cars.py 路由**

```python
# app/routers/cars.py
from typing import Optional
from pathlib import Path
import uuid
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from app import config
from app.db import get_session
from app.models import Team
from app.enums import Category
from app.services import cars as csvc, teams as tsvc
from app.routers.pages import templates

router = APIRouter()


def _save_image(image: Optional[UploadFile]) -> Optional[str]:
    if image is None or not image.filename:
        return None
    ext = Path(image.filename).suffix.lower() or ".png"
    fname = f"{uuid.uuid4().hex}{ext}"
    dest = config.IMAGES_DIR / fname
    dest.write_bytes(image.file.read())
    return fname


def _teams(session: Session):
    return session.exec(select(Team).order_by(Team.name)).all()


@router.get("/cars/new", response_class=HTMLResponse)
def new_car(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse("car_form.html", {
        "request": request, "car": None, "teams": _teams(session),
        "action": "/cars", "error": None})


@router.post("/cars")
def create_car(request: Request, nickname: str = Form(...), category: str = Form(...),
               brand: str = Form(""), casting: str = Form(""),
               description: str = Form(""), team_id: str = Form(""),
               image: UploadFile = File(None),
               session: Session = Depends(get_session)):
    try:
        car = csvc.create_car(
            session, nickname=nickname, category=Category(category), brand=brand,
            casting=casting, description=description,
            team_id=int(team_id) if team_id else None,
            image_path=_save_image(image))
        return RedirectResponse(f"/cars/{car.id}", status_code=303)
    except (csvc.CarValidationError, tsvc.TeamValidationError) as e:
        return templates.TemplateResponse("car_form.html", {
            "request": request, "car": None, "teams": _teams(session),
            "action": "/cars", "error": str(e)}, status_code=200)


@router.get("/cars/{car_id}/edit", response_class=HTMLResponse)
def edit_car_form(car_id: int, request: Request,
                  session: Session = Depends(get_session)):
    from app.models import Car
    car = session.get(Car, car_id)
    return templates.TemplateResponse("car_form.html", {
        "request": request, "car": car, "teams": _teams(session),
        "action": f"/cars/{car_id}/edit", "error": None})


@router.post("/cars/{car_id}/edit")
def edit_car(car_id: int, request: Request, nickname: str = Form(...),
             category: str = Form(...), brand: str = Form(""), casting: str = Form(""),
             description: str = Form(""), team_id: str = Form(""),
             image: UploadFile = File(None),
             session: Session = Depends(get_session)):
    from app.models import Car
    fields = dict(nickname=nickname, category=Category(category), brand=brand,
                  casting=casting, description=description,
                  team_id=int(team_id) if team_id else None)
    img = _save_image(image)
    if img:
        fields["image_path"] = img
    try:
        csvc.update_car(session, car_id, **fields)
        return RedirectResponse(f"/cars/{car_id}", status_code=303)
    except (csvc.CarValidationError, tsvc.TeamValidationError) as e:
        car = session.get(Car, car_id)
        return templates.TemplateResponse("car_form.html", {
            "request": request, "car": car, "teams": _teams(session),
            "action": f"/cars/{car_id}/edit", "error": str(e)}, status_code=200)
```

- [ ] **Step 6: 写最小 car_detail.html(下一任务完善)**

```html
<!-- app/templates/car_detail.html -->
{% extends "base.html" %}
{% block content %}
<div class="card"><h2>{{ car.nickname }}</h2></div>
{% endblock %}
```

并在 `cars.py` 追加详情路由:

```python
@router.get("/cars/{car_id}", response_class=HTMLResponse)
def car_detail(car_id: int, request: Request,
               session: Session = Depends(get_session)):
    from app.models import Car
    car = session.get(Car, car_id)
    return templates.TemplateResponse("car_detail.html", {
        "request": request, "car": car})
```

> 路由顺序:确保 `/cars/new` 在 `/cars/{car_id}` 之前定义,避免 "new" 被当作 id。

- [ ] **Step 7: 运行测试确认通过**

Run: `pytest tests/test_cars_routes.py -v`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add app/routers/cars.py app/templates/car_form.html app/templates/car_detail.html app/main.py tests/test_cars_routes.py
git commit -m "feat: car create/edit form with image upload"
```

---

## Task 11: 车队新增/编辑表单

**Files:**
- Modify: `app/routers/teams.py`
- Create: `app/templates/team_form.html`, `app/templates/team_detail.html`(最小)
- Test: `tests/test_teams_routes.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_teams_routes.py
from fastapi.testclient import TestClient
from app.main import app
from sqlmodel import select
from app.models import Team

client = TestClient(app)


def test_create_factory_team(engine, session):
    r = client.post("/teams", data={"type": "厂商车队", "brand": "法拉利", "name": ""},
                    follow_redirects=False)
    assert r.status_code in (302, 303)
    t = session.exec(select(Team)).one()
    assert t.name == "法拉利车队"


def test_create_factory_without_brand_errors(engine, session):
    r = client.post("/teams", data={"type": "厂商车队", "brand": "", "name": ""})
    assert r.status_code == 200
    assert "品牌" in r.text


def test_create_independent_team(engine, session):
    r = client.post("/teams", data={"type": "独立车队", "brand": "", "name": "车库突击队"},
                    follow_redirects=False)
    assert r.status_code in (302, 303)
    assert session.exec(select(Team)).one().name == "车库突击队"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_teams_routes.py -v`
Expected: FAIL(404)

- [ ] **Step 3: 写 team_form.html**

```html
<!-- app/templates/team_form.html -->
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h2>{{ "编辑车队" if team else "新增车队" }}</h2>
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
  <form method="post" action="{{ action }}">
    <label>类型</label>
    <select name="type">
      <option value="厂商车队" {{ "selected" if team and team.type.value=="厂商车队" else "" }}>厂商车队</option>
      <option value="独立车队" {{ "selected" if team and team.type.value=="独立车队" else "" }}>独立车队</option>
    </select>
    <label>品牌(厂商车队填)</label>
    <input name="brand" value="{{ team.brand if team and team.brand else "" }}">
    <label>名称(独立车队填)</label>
    <input name="name" value="{{ team.name if team and team.type.value=="独立车队" else "" }}">
    <div style="margin-top:12px"><button class="btn" type="submit">保存</button></div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 4: 写 team_detail.html(最小,下一任务完善)**

```html
<!-- app/templates/team_detail.html -->
{% extends "base.html" %}
{% block content %}
<div class="card"><h2>{{ team.name }}</h2></div>
{% endblock %}
```

- [ ] **Step 5: 写 teams.py 路由**

```python
# app/routers/teams.py
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session
from app.db import get_session
from app.models import Team
from app.enums import TeamType
from app.services import teams as tsvc
from app.routers.pages import templates

router = APIRouter()


@router.get("/teams/new", response_class=HTMLResponse)
def new_team(request: Request):
    return templates.TemplateResponse("team_form.html", {
        "request": request, "team": None, "action": "/teams", "error": None})


@router.post("/teams")
def create_team(request: Request, type: str = Form(...), brand: str = Form(""),
                name: str = Form(""), session: Session = Depends(get_session)):
    try:
        team = tsvc.create_team(session, type=TeamType(type),
                                brand=brand or None, name=name or None)
        return RedirectResponse(f"/teams/{team.id}", status_code=303)
    except tsvc.TeamValidationError as e:
        return templates.TemplateResponse("team_form.html", {
            "request": request, "team": None, "action": "/teams",
            "error": str(e)}, status_code=200)


@router.get("/teams/{team_id}", response_class=HTMLResponse)
def team_detail(team_id: int, request: Request,
                session: Session = Depends(get_session)):
    team = session.get(Team, team_id)
    return templates.TemplateResponse("team_detail.html", {
        "request": request, "team": team})
```

> 路由顺序:`/teams/new` 必须在 `/teams/{team_id}` 之前定义。

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/test_teams_routes.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add app/routers/teams.py app/templates/team_form.html app/templates/team_detail.html tests/test_teams_routes.py
git commit -m "feat: team create form"
```

---

## Task 12: 完善赛车 / 车队个人页(实时生成)

**Files:**
- Modify: `app/templates/car_detail.html`, `app/templates/team_detail.html`
- Modify: `app/routers/cars.py`, `app/routers/teams.py`(补齐模板上下文)
- Test: `tests/test_pages.py`(追加)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pages.py 追加
def test_car_detail_shows_fields(engine, session):
    csvc.create_car(session, nickname="红色闪电", category=Category.GT3,
                    brand="法拉利", casting="C01", description="弯道稳定", team_id=None)
    from app.models import Car
    cid = session.exec(select(Car)).one().id
    r = client.get(f"/cars/{cid}")
    assert "红色闪电" in r.text and "弯道稳定" in r.text and "1500" in r.text


def test_team_detail_shows_capacity(engine, session):
    t = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    csvc.create_car(session, nickname="红色闪电", category=Category.GT3,
                    brand="法拉利", casting="", description="", team_id=t.id)
    r = client.get(f"/teams/{t.id}")
    assert "法拉利车队" in r.text and "红色闪电" in r.text
```

(顶部需 `from sqlmodel import select`,已在前面任务引入。)

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_pages.py -k "car_detail or team_detail" -v`
Expected: FAIL(断言文本缺失)

- [ ] **Step 3: 完善 car_detail.html**

```html
<!-- app/templates/car_detail.html -->
{% extends "base.html" %}
{% block content %}
<div class="card">
  <div style="display:flex;gap:16px">
    {% if car.image_path %}<img src="/static/uploads/{{ car.image_path }}" style="width:120px;height:90px;object-fit:cover;border-radius:8px">
    {% else %}<span class="thumb" style="width:120px;height:90px"></span>{% endif %}
    <div style="flex:1">
      <h2 style="margin:0">{{ car.nickname }} <span class="tag">{{ car.category.value }}</span></h2>
      <p><small>{{ car.casting }} · {{ car.brand }} · 车队:{{ team_name or "无车队" }}</small></p>
      <a class="btn" href="/cars/{{ car.id }}/edit">编辑</a>
    </div>
  </div>
  <p>{{ car.description }}</p>
  <div class="grid">
    <div class="stat"><div class="label">赛季 MMR</div><div class="value">{{ car.season_mmr | round | int }}</div></div>
    <div class="stat"><div class="label">{{ car.category.value }} 排名</div><div class="value">#{{ rank or "-" }}</div></div>
    <div class="stat"><div class="label">历史 MMR</div><div class="value">{{ car.historical_mmr | round | int }}</div></div>
  </div>
  <h3>历史战绩 / 荣誉</h3>
  {% for line in honors %}<p>{{ line }}</p>{% else %}<p>暂无记录</p>{% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 4: 更新 cars.py 详情路由上下文**

把 Task 10 的 `car_detail` 路由替换为:

```python
@router.get("/cars/{car_id}", response_class=HTMLResponse)
def car_detail(car_id: int, request: Request,
               session: Session = Depends(get_session)):
    from app.models import Car
    car = session.get(Car, car_id)
    team_name = None
    if car.team_id:
        t = session.get(Team, car.team_id)
        team_name = t.name if t else None
    # 同类别按赛季 MMR 排名
    same = session.exec(select(Car).where(Car.category == car.category)
                        .order_by(Car.season_mmr.desc())).all()
    rank = next((i + 1 for i, c in enumerate(same) if c.id == car.id), None)
    honors: list[str] = []   # 计划二/三填充真实战绩
    return templates.TemplateResponse("car_detail.html", {
        "request": request, "car": car, "team_name": team_name,
        "rank": rank, "honors": honors})
```

- [ ] **Step 5: 完善 team_detail.html**

```html
<!-- app/templates/team_detail.html -->
{% extends "base.html" %}
{% block content %}
<div class="card">
  <div style="display:flex;justify-content:space-between">
    <h2 style="margin:0">{{ team.name }}</h2>
    <a class="btn" href="/teams/{{ team.id }}/edit">编辑</a>
  </div>
  <p><small>{{ team.type.value }}{% if team.brand %} · 品牌:{{ team.brand }}{% endif %}</small></p>
  <div class="grid">
    <div class="stat"><div class="label">本赛季积分</div><div class="value">{{ season_points }}</div></div>
    <div class="stat"><div class="label">成员车</div><div class="value">{{ members|length }}</div></div>
  </div>
  <h3>成员赛车(按类别)</h3>
  {% for c in members %}
  <div class="row"><span style="flex:1">{{ c.nickname }}</span><span class="tag">{{ c.category.value }}</span></div>
  {% else %}<p>暂无成员</p>{% endfor %}
  {% for cat, used in capacity.items() %}
  <p><small>{{ cat }} {{ used }}/2</small></p>
  {% endfor %}
  <h3>本赛季积分来源</h3>
  {% for line in point_sources %}<p>{{ line }}</p>{% else %}<p>暂无</p>{% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 6: 更新 teams.py 详情路由上下文**

把 Task 11 的 `team_detail` 路由替换为:

```python
@router.get("/teams/{team_id}", response_class=HTMLResponse)
def team_detail(team_id: int, request: Request,
                session: Session = Depends(get_session)):
    from app.models import Car
    from app.config import MAX_CARS_PER_CATEGORY
    team = session.get(Team, team_id)
    members = session.exec(select(Car).where(Car.team_id == team_id)
                           .order_by(Car.category)).all()
    capacity: dict[str, int] = {}
    for c in members:
        capacity[c.category.value] = capacity.get(c.category.value, 0) + 1
    return templates.TemplateResponse("team_detail.html", {
        "request": request, "team": team, "members": members,
        "capacity": capacity, "season_points": 0,      # 计划三填充
        "point_sources": []})                          # 计划三填充
```

需在 teams.py 顶部确保 `from sqlmodel import select` 已导入。

- [ ] **Step 7: 运行测试确认通过**

Run: `pytest tests/test_pages.py -v`
Expected: PASS

- [ ] **Step 8: 全量回归 + 提交**

Run: `pytest -v`
Expected: 全部 PASS

```bash
git add app/templates/car_detail.html app/templates/team_detail.html app/routers/cars.py app/routers/teams.py tests/test_pages.py
git commit -m "feat: car and team detail pages"
```

---

## Task 13: 赛季页面(列表 + 结束/开启)

**Files:**
- Modify: `app/routers/seasons.py`
- Create: `app/templates/seasons.html`, `app/templates/season_detail.html`(最小)
- Test: `tests/test_seasons_service.py`(追加路由测试)或新 `tests/test_seasons_routes.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_seasons_routes.py
from fastapi.testclient import TestClient
from app.main import app
from app.services import seasons as svc

client = TestClient(app)


def test_seasons_page_lists(engine, session):
    svc.start_season(session, name="2026 S1")
    r = client.get("/seasons")
    assert r.status_code == 200 and "2026 S1" in r.text


def test_start_season_via_post(engine, session):
    r = client.post("/seasons", data={"name": "2026 S1"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert svc.get_active_season(session).name == "2026 S1"


def test_end_season_via_post(engine, session):
    s = svc.start_season(session, name="2026 S1")
    r = client.post(f"/seasons/{s.id}/end", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert svc.get_active_season(session) is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_seasons_routes.py -v`
Expected: FAIL(404)

- [ ] **Step 3: 写 seasons.html**

```html
<!-- app/templates/seasons.html -->
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h2>赛季</h2>
  {% if not active %}
  <form method="post" action="/seasons" style="display:flex;gap:8px">
    <input name="name" placeholder="新赛季名称,如 2026 S1" required>
    <button class="btn">开启新赛季</button>
  </form>
  {% else %}
  <p>当前赛季:<strong>{{ active.name }}</strong>(进行中)
    <form method="post" action="/seasons/{{ active.id }}/end" style="display:inline">
      <button class="btn">结束当前赛季</button>
    </form>
  </p>
  {% endif %}
  {% for s in seasons %}
  <a class="row" href="/seasons/{{ s.id }}"><span style="flex:1">{{ s.name }}</span><span class="tag">{{ s.status.value }}</span></a>
  {% else %}<p>暂无赛季</p>{% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 4: 写 season_detail.html(最小,计划三完善)**

```html
<!-- app/templates/season_detail.html -->
{% extends "base.html" %}
{% block content %}
<div class="card"><h2>{{ season.name }}</h2><p>{{ season.status.value }}</p></div>
{% endblock %}
```

- [ ] **Step 5: 写 seasons.py 路由**

```python
# app/routers/seasons.py
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from app.db import get_session
from app.models import Season
from app.services import seasons as svc
from app.routers.pages import templates

router = APIRouter()


@router.get("/seasons", response_class=HTMLResponse)
def seasons_page(request: Request, session: Session = Depends(get_session)):
    seasons = session.exec(select(Season).order_by(Season.id.desc())).all()
    return templates.TemplateResponse("seasons.html", {
        "request": request, "seasons": seasons,
        "active": svc.get_active_season(session)})


@router.post("/seasons")
def start_season(request: Request, name: str = Form(...),
                 session: Session = Depends(get_session)):
    try:
        svc.start_season(session, name=name)
    except svc.SeasonError:
        pass
    return RedirectResponse("/seasons", status_code=303)


@router.post("/seasons/{season_id}/end")
def end_season(season_id: int, session: Session = Depends(get_session)):
    try:
        svc.end_season(session, season_id)
    except svc.SeasonError:
        pass
    return RedirectResponse("/seasons", status_code=303)


@router.get("/seasons/{season_id}", response_class=HTMLResponse)
def season_detail(season_id: int, request: Request,
                  session: Session = Depends(get_session)):
    season = session.get(Season, season_id)
    return templates.TemplateResponse("season_detail.html", {
        "request": request, "season": season})
```

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/test_seasons_routes.py -v`
Expected: PASS

- [ ] **Step 7: 全量回归 + 提交**

Run: `pytest -v`
Expected: 全部 PASS

```bash
git add app/routers/seasons.py app/templates/seasons.html app/templates/season_detail.html tests/test_seasons_routes.py
git commit -m "feat: season pages and lifecycle routes"
```

---

## 自检(写计划后已核对)

- **Spec 覆盖**:数据模型(Task 3)、车队约束(Task 4)、赛车增改(Task 5、10)、全字段搜索(Task 6、9)、统一列表页+标签(Task 9)、个人页实时生成(Task 12)、赛季页与结束/开启(Task 7、13)、图片存储(Task 10)。MMR/积分结算与赛事流程留给计划二、三(已在 spec §7 注明)。
- **占位扫描**:`honors`/`season_points`/`point_sources` 在本计划留空数组并注释「计划二/三填充」,非隐藏的 TODO,而是明确的跨计划接口。`end_season` 的快照钩子位置已标注。
- **类型一致**:服务异常 `TeamValidationError`/`CarValidationError`/`SeasonError` 在定义与捕获处名称一致;`get_active_season`/`start_season`/`end_season`/`search_cars`/`search_teams`/`check_can_assign`/`create_car`/`update_car` 签名前后一致。
