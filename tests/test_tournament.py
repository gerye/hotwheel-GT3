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


from app.models import TieBreak


def _read_results(session, group_id):
    from app.models import Heat
    out: dict[int, list] = {}
    heats = session.exec(select(Heat).where(Heat.group_id == group_id)).all()
    for h in heats:
        for r in session.exec(select(HeatResult).where(HeatResult.heat_id == h.id)).all():
            out.setdefault(r.car_id, []).append(r.rank)
    return out


def test_group_advancement_no_tie(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 4)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    grp = session.exec(select(Group)).first()
    # 让 cars[0] 全 1、cars[1] 全 2、cars[2] 全 3、cars[3] 全 4
    heats = session.exec(select(Heat).where(Heat.group_id == grp.id)).all()
    for h in heats:
        T.record_heat(session, h.id,
                      ranks={cars[0]: 1, cars[1]: 2, cars[2]: 3, cars[3]: 4})
    adv = T.settle_group(session, grp.id)
    assert adv.advancers == [cars[0], cars[1]]


def test_group_tie_needs_decision_then_resolved(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 4)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    grp = session.exec(select(Group)).first()
    heats = sorted(session.exec(select(Heat).where(Heat.group_id == grp.id)).all(),
                   key=lambda h: h.number)
    # cars[0] 稳第一;cars[1] 与 cars[2] 打平争第二
    plans = [
        {cars[0]: 1, cars[1]: 2, cars[2]: 3, cars[3]: 4},
        {cars[0]: 1, cars[1]: 3, cars[2]: 2, cars[3]: 4},
        {cars[0]: 1, cars[1]: 2, cars[2]: 3, cars[3]: 4},
        {cars[0]: 1, cars[1]: 3, cars[2]: 2, cars[3]: 4},
    ]
    for h, p in zip(heats, plans):
        T.record_heat(session, h.id, ranks=p)
    adv = T.settle_group(session, grp.id)
    assert adv.advancers is None
    assert set(adv.tie_between) == {cars[1], cars[2]}
    T.resolve_tie(session, grp.id, winner_car_id=cars[2])
    adv2 = T.settle_group(session, grp.id)
    assert adv2.advancers == [cars[0], cars[2]]


def test_advance_to_next_round_until_final(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 6)   # 3,3 -> 晋级4 -> 决赛组4
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    # 录入所有第一轮小组,使每组前两名确定(用站位顺序当名次)
    r1 = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).first()
    for grp in session.exec(select(Group).where(Group.round_id == r1.id)).all():
        members = [m.car_id for m in session.exec(select(GroupMember)
                   .where(GroupMember.group_id == grp.id)).all()]
        for h in session.exec(select(Heat).where(Heat.group_id == grp.id)).all():
            T.record_heat(session, h.id,
                          ranks={c: i + 1 for i, c in enumerate(members)})
    result = T.advance_round(session, race.id, seed=2)
    assert result.kind == "next_round"
    rounds = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).all()
    assert len(rounds) == 2
    final = [r for r in rounds if r.number == 2][0]
    assert final.is_final is True


def test_final_round_produces_ranking_and_finishes(session):
    ssvc.start_season(session, name="2026 S1")
    cars = _make_cars(session, 4)   # 直接就是决赛组
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=cars, seed=1)
    r1 = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).first()
    grp = session.exec(select(Group).where(Group.round_id == r1.id)).first()
    members = [m.car_id for m in session.exec(select(GroupMember)
               .where(GroupMember.group_id == grp.id)).all()]
    for h in session.exec(select(Heat).where(Heat.group_id == grp.id)).all():
        T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(members)})
    result = T.advance_round(session, race.id, seed=2)
    assert result.kind == "finished"
    assert result.ranking == members         # 名次 = 总分序
    from app.models import Race
    assert session.get(Race, race.id).status.value == "已结束"
