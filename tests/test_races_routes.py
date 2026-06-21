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
    r = client.get("/races/new?category=GT3&pro_level=表演&format=单人锦标赛")
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
