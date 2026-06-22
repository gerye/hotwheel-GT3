from fastapi.testclient import TestClient
from app.main import app
from app.services import seasons as ssvc, cars as csvc, teams as tsvc
from app.enums import Category, TeamType
from sqlmodel import select
from app.models import Race, Group, Heat, HeatResult, GroupMember, RaceRound

client = TestClient(app)


def _cars(session, n):
    ids = []
    for i in range(n):
        c = csvc.create_car(session, nickname=f"车{i}", category=Category.GT3,
                            brand="法拉利", casting="", description="", team_id=None)
        ids.append(c.id)
    return ids


def _teams_with_cars(session, n, *, cars_per_team=1):
    """建 n 支独立车队,每队 cars_per_team 辆 GT3 车,返回 team_ids。"""
    team_ids = []
    for t in range(n):
        team = tsvc.create_team(session, type=TeamType.INDEPENDENT,
                                brand=None, name=f"车队{t}")
        for c in range(cars_per_team):
            csvc.create_car(session, nickname=f"队{t}车{c}", category=Category.GT3,
                            brand="法拉利", casting="", description="",
                            team_id=team.id)
        team_ids.append(team.id)
    return team_ids


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


def test_new_team_race_page_lists_teams(engine, session):
    ssvc.start_season(session, name="2026 S1")
    _teams_with_cars(session, 2)
    r = client.get("/races/new?category=GT3&pro_level=专业&format=车队锦标赛")
    assert r.status_code == 200
    assert "车队0" in r.text and "车队1" in r.text
    # 车队赛勾选项提交 team_ids,不是 car_ids
    assert 'name="team_ids"' in r.text


def test_create_team_race_builds_paired_groups(engine, session):
    ssvc.start_season(session, name="2026 S1")
    team_ids = _teams_with_cars(session, 4)     # 4 队 → 2 组,每组 2 队
    r = client.post("/races", data={"category": "GT3", "pro_level": "专业",
        "format": "车队锦标赛", "team_ids": [str(i) for i in team_ids]},
        follow_redirects=False)
    assert r.status_code in (302, 303)
    race = session.exec(select(Race)).one()
    assert race.format.value == "车队锦标赛"
    rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).one()
    groups = session.exec(select(Group).where(Group.round_id == rnd.id)).all()
    assert len(groups) == 2
    for g in groups:
        assert g.team_a_id is not None and g.team_b_id is not None
        assert g.team_a_id != g.team_b_id
    # 每组的两队应覆盖全部 4 队
    paired = {g.team_a_id for g in groups} | {g.team_b_id for g in groups}
    assert paired == set(team_ids)
    page = client.get(f"/races/{race.id}")
    assert page.status_code == 200


def test_team_advance_builds_team_next_round(engine, session):
    ssvc.start_season(session, name="2026 S1")
    team_ids = _teams_with_cars(session, 4)     # 4 队 → 2 组 → 晋级 2 队 → 决赛组
    client.post("/races", data={"category": "GT3", "pro_level": "专业",
        "format": "车队锦标赛", "team_ids": [str(i) for i in team_ids]})
    race = session.exec(select(Race)).one()
    _record_all(session, race.id)
    r = client.post(f"/races/{race.id}/advance", follow_redirects=False)
    assert r.status_code in (302, 303)
    rounds = session.exec(select(RaceRound).where(
        RaceRound.race_id == race.id).order_by(RaceRound.number)).all()
    assert len(rounds) == 2
    final = rounds[-1]
    assert final.is_final is True
    groups = session.exec(select(Group).where(Group.round_id == final.id)).all()
    assert len(groups) == 1
    # 决赛组仍是 2 个车队组成
    assert groups[0].team_a_id is not None and groups[0].team_b_id is not None


def test_team_race_finishes_with_team_ranking(engine, session):
    ssvc.start_season(session, name="2026 S1")
    team_ids = _teams_with_cars(session, 2)     # 2 队即决赛组
    client.post("/races", data={"category": "GT3", "pro_level": "专业",
        "format": "车队锦标赛", "team_ids": [str(i) for i in team_ids]})
    race = session.exec(select(Race)).one()
    _record_all(session, race.id)
    client.post(f"/races/{race.id}/advance")
    session.refresh(race)
    assert race.status.value == "已结束"


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
