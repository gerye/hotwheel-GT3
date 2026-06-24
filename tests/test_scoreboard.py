from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import select
from app.main import app
from app.enums import Category, ProLevel, RaceFormat, TeamType
from app.services import seasons as ssvc, teams as tsvc, cars as csvc, tournament as T
from app.models import Group, GroupMember, Heat, Race


def _solo_group(session, n=4):
    ssvc.start_season(session, name="2026 S1")
    ids = []
    for i in range(n):
        t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name=f"q{i}")
        c = csvc.create_car(session, nickname=f"c{i}", category=Category.GT3,
                            brand="B", casting="", description="", team_id=t.id)
        ids.append(c.id)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=ids, seed=1)
    grp = session.exec(select(Group)).first()
    members = [m.car_id for m in session.exec(select(GroupMember)
               .where(GroupMember.group_id == grp.id)).all()]
    return race, grp, members


def _heats(session, group_id):
    return session.exec(select(Heat).where(Heat.group_id == group_id)
                        .order_by(Heat.number)).all()


def test_solo_board_sorted_and_points(session):
    race, grp, m = _solo_group(session)
    heats = _heats(session, grp.id)
    # 第1场:m0=1,m1=2,m2=3,m3=4
    T.record_heat(session, heats[0].id,
                  ranks={m[0]: 1, m[1]: 2, m[2]: 3, m[3]: 4})
    board = T.group_scoreboard(session, grp, race)
    assert board["is_team"] is False and board["n_heats"] == 4
    # 领先者是 m0(5 分),降序
    assert board["rows"][0]["total"] == 5
    assert board["rows"][0]["heats"][0] == 5
    assert [r["total"] for r in board["rows"]] == sorted(
        [r["total"] for r in board["rows"]], reverse=True)
    # 未录入的场为 0
    assert board["rows"][0]["heats"][1] == 0


def test_team_board_groups_and_sorts(session):
    ssvc.start_season(session, name="2026 S1")
    t1 = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    t2 = tsvc.create_team(session, type=TeamType.FACTORY, brand="保时捷", name=None)
    for t, b in [(t1, "法拉利"), (t2, "保时捷")]:
        for i in range(2):
            csvc.create_car(session, nickname=f"{b}{i}", category=Category.GT3,
                            brand=b, casting="", description="", team_id=t.id)
    race = T.create_team_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                              team_ids=[t1.id, t2.id], seed=1)
    grp = session.exec(select(Group)).first()
    members = [m.car_id for m in session.exec(select(GroupMember)
               .where(GroupMember.group_id == grp.id)).all()]
    fer = set(c.id for c in session.exec(select(__import__('app.models', fromlist=['Car']).Car)
              .where(__import__('app.models', fromlist=['Car']).Car.team_id == t1.id)).all())
    # 让法拉利两车包揽前二,每场都是
    for h in _heats(session, grp.id):
        ordered = [c for c in members if c in fer] + [c for c in members if c not in fer]
        T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(ordered)})
    board = T.group_scoreboard(session, grp, race)
    assert board["is_team"] is True
    assert len(board["teams"]) == 2
    # 法拉利车队总分最高,排第一,且其下两辆车
    assert board["teams"][0]["total"] >= board["teams"][1]["total"]
    assert "法拉利" in board["teams"][0]["name"]
    assert len(board["teams"][0]["cars"]) == 2


def test_single_car_team_total_doubled(session):
    ssvc.start_season(session, name="2026 S1")
    t1 = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    t2 = tsvc.create_team(session, type=TeamType.FACTORY, brand="保时捷", name=None)
    csvc.create_car(session, nickname="法1", category=Category.GT3, brand="法拉利",
                    casting="", description="", team_id=t1.id)        # 1 车
    for i in range(2):
        csvc.create_car(session, nickname=f"保{i}", category=Category.GT3, brand="保时捷",
                        casting="", description="", team_id=t2.id)
    race = T.create_team_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                              team_ids=[t1.id, t2.id], seed=1)
    grp = session.exec(select(Group)).first()
    members = [m.car_id for m in session.exec(select(GroupMember)
               .where(GroupMember.group_id == grp.id)).all()]
    for h in _heats(session, grp.id):
        T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(members)})
    board = T.group_scoreboard(session, grp, race)
    by_name = {t["name"]: t for t in board["teams"]}
    fer = [t for n, t in by_name.items() if "法拉利" in n][0]
    # 1 车队伍:车小计之和 ×2 == 车队总分
    assert fer["total"] == sum(c["total"] for c in fer["cars"]) * 2


def test_scoreboard_renders_on_race_page(engine, session):
    race, grp, m = _solo_group(session)
    client = TestClient(app)
    r = client.get(f"/races/{race.id}")
    assert r.status_code == 200
    assert "第1场" in r.text and "总分" in r.text
