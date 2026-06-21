from app.models import Race, RaceRound, Group, Heat, HeatResult
from app.enums import Category, ProLevel, RaceFormat


def test_race_tables_exist(session):
    from app.services import seasons as ssvc
    s = ssvc.start_season(session, name="2026 S1")
    r = Race(season_id=s.id, category=Category.GT3,
             pro_level=ProLevel.PRO, format=RaceFormat.SOLO)
    session.add(r); session.commit(); session.refresh(r)
    assert r.id is not None and r.status.value == "进行中"


from app.services import tournament as T, seasons as ssvc, cars as csvc
from sqlmodel import select
from app.models import RaceRound, Group, GroupMember, Heat, HeatResult


def _make_cars(session, n, category=Category.GT3):
    ids = []
    for i in range(n):
        c = csvc.create_car(session, nickname=f"车{i}", category=category,
                            brand="法拉利", casting="", description="", team_id=None)
        ids.append(c.id)
    return ids


def test_create_solo_race_builds_first_round(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 6)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    rounds = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).all()
    assert len(rounds) == 1 and rounds[0].number == 1
    groups = session.exec(select(Group).where(Group.round_id == rounds[0].id)).all()
    assert sorted(len(session.exec(select(GroupMember).where(
        GroupMember.group_id == grp.id)).all()) for grp in groups) == [3, 3]


def test_each_group_has_four_heats_with_lanes(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 4)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    grp = session.exec(select(Group)).first()
    heats = session.exec(select(Heat).where(Heat.group_id == grp.id)).all()
    assert len(heats) == 4
    h1 = sorted(heats, key=lambda h: h.number)[0]
    rows = session.exec(select(HeatResult).where(HeatResult.heat_id == h1.id)).all()
    assert sorted(r.lane for r in rows) == [1, 2, 3, 4]


def test_create_race_rejects_five_cars(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 5)
    import pytest
    from app.services.grouping import GroupingError
    with pytest.raises(GroupingError):
        T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                      format=RaceFormat.SOLO, car_ids=cars, seed=1)


def _record_group(session, group_id, order):
    """order: 每场 [道1车,道2车,...] 的名次按给定 car 顺序 1..k。这里简化为给每场同一名次顺序。"""
    from app.models import Heat
    heats = session.exec(select(Heat).where(Heat.group_id == group_id)
                         .order_by(Heat.number)).all()
    for h in heats:
        T.record_heat(session, h.id, ranks={car: pos + 1 for pos, car in enumerate(order)})


def test_record_heat_sets_ranks_and_recorded(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 4)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    grp = session.exec(select(Group)).first()
    h1 = session.exec(select(Heat).where(Heat.group_id == grp.id)
                      .order_by(Heat.number)).first()
    T.record_heat(session, h1.id, ranks={cars[0]: 1, cars[1]: 2, cars[2]: 3, cars[3]: 4})
    session.refresh(h1)
    assert h1.recorded is True
    rows = session.exec(select(HeatResult).where(HeatResult.heat_id == h1.id)).all()
    assert {r.car_id: r.rank for r in rows}[cars[0]] == 1


def test_undo_heat_clears_ranks(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 4)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    grp = session.exec(select(Group)).first()
    h1 = session.exec(select(Heat).where(Heat.group_id == grp.id)
                      .order_by(Heat.number)).first()
    T.record_heat(session, h1.id, ranks={cars[0]: 1, cars[1]: 2, cars[2]: 3, cars[3]: 4})
    T.undo_heat(session, h1.id)
    session.refresh(h1)
    assert h1.recorded is False
    rows = session.exec(select(HeatResult).where(HeatResult.heat_id == h1.id)).all()
    assert all(r.rank is None and r.dnf is False for r in rows)


def test_record_heat_with_dnf(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 4)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    grp = session.exec(select(Group)).first()
    h1 = session.exec(select(Heat).where(Heat.group_id == grp.id)
                      .order_by(Heat.number)).first()
    T.record_heat(session, h1.id, ranks={cars[0]: 1, cars[1]: 2, cars[2]: 3},
                  dnf={cars[3]})
    rows = session.exec(select(HeatResult).where(HeatResult.heat_id == h1.id)).all()
    by_car = {r.car_id: r for r in rows}
    assert by_car[cars[3]].dnf is True and by_car[cars[3]].rank is None
