from __future__ import annotations

import pytest
from sqlmodel import select
from app.enums import Category, ProLevel, RaceFormat, TeamType
from app.services import seasons as ssvc, teams as tsvc, cars as csvc, tournament as T
from app.models import Group, GroupMember, Heat


def _setup_group(session):
    ssvc.start_season(session, name="2026 S1")
    ids = []
    for i in range(4):
        t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name=f"q{i}")
        c = csvc.create_car(session, nickname=f"c{i}", category=Category.GT3,
                            brand="B", casting="", description="", team_id=t.id)
        ids.append(c.id)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=ids, seed=1)
    grp = session.exec(select(Group)).first()
    members = [m.car_id for m in session.exec(select(GroupMember)
               .where(GroupMember.group_id == grp.id)).all()]
    heat = session.exec(select(Heat).where(Heat.group_id == grp.id)
                        .order_by(Heat.number)).first()
    return heat.id, members


def test_duplicate_rank_rejected(session):
    hid, m = _setup_group(session)
    with pytest.raises(T.HeatInputError):
        T.record_heat(session, hid, ranks={m[0]: 1, m[1]: 1, m[2]: 3, m[3]: 4})


def test_rank_and_dnf_together_rejected(session):
    hid, m = _setup_group(session)
    with pytest.raises(T.HeatInputError):
        T.record_heat(session, hid, ranks={m[0]: 1, m[1]: 2, m[2]: 3, m[3]: 4},
                      dnf={m[0]})


def test_blank_entry_rejected(session):
    hid, m = _setup_group(session)
    with pytest.raises(T.HeatInputError):       # m[3] 既无名次也未勾未完赛
        T.record_heat(session, hid, ranks={m[0]: 1, m[1]: 2, m[2]: 3})


def test_gap_in_ranks_rejected(session):
    hid, m = _setup_group(session)
    with pytest.raises(T.HeatInputError):       # 1,2,3,5 缺号
        T.record_heat(session, hid, ranks={m[0]: 1, m[1]: 2, m[2]: 3, m[3]: 5})


def test_valid_full_ranks_ok(session):
    hid, m = _setup_group(session)
    T.record_heat(session, hid, ranks={m[0]: 1, m[1]: 2, m[2]: 3, m[3]: 4})
    h = session.get(Heat, hid)
    assert h.recorded is True


def test_valid_with_dnf_ok(session):
    hid, m = _setup_group(session)
    # 一辆未完赛,其余 1,2,3
    T.record_heat(session, hid, ranks={m[0]: 1, m[1]: 2, m[2]: 3}, dnf={m[3]})
    assert session.get(Heat, hid).recorded is True


def test_invalid_input_via_route_shows_error(engine, session):
    from fastapi.testclient import TestClient
    from app.main import app
    hid, m = _setup_group(session)
    client = TestClient(app)
    data = {f"rank_{m[0]}": "1", f"rank_{m[1]}": "1",   # 两个第一
            f"rank_{m[2]}": "3", f"rank_{m[3]}": "4"}
    r = client.post(f"/races/1/heats/{hid}", data=data, follow_redirects=False)
    assert r.status_code == 303
    assert "err=" in r.headers["location"]
    session.expire_all()
    assert session.get(Heat, hid).recorded is False    # 未被记录,要求重录
