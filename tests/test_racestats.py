from __future__ import annotations

from sqlmodel import select
from app.enums import Category, ProLevel, RaceFormat, TeamType
from app.services import seasons as ssvc, teams as tsvc, cars as csvc, tournament as T
from app.services import racestats
from app.models import Race, RaceRound, Group, GroupMember, Heat


def _run_solo_6(session):
    ssvc.start_season(session, name="S1")
    ids = []
    for i in range(6):
        t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name=f"q{i}")
        ids.append(csvc.create_car(session, nickname=f"c{i}", category=Category.GT3,
                   brand="B", casting="", description="", team_id=t.id).id)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=ids, seed=1)
    # 逐轮按"组内成员顺序即名次"录完,直到结束
    while True:
        rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)
                           .order_by(RaceRound.number.desc())).first()
        for g in session.exec(select(Group).where(Group.round_id == rnd.id)).all():
            members = [m.car_id for m in session.exec(select(GroupMember)
                       .where(GroupMember.group_id == g.id)).all()]
            for h in session.exec(select(Heat).where(Heat.group_id == g.id)).all():
                T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(members)})
        res = T.advance_round(session, race.id, seed=2)
        if res.kind == "finished":
            return race, ids, res.ranking


def test_advancements_and_champion(session):
    race, ids, ranking = _run_solo_6(session)
    adv = racestats.car_advancements(session, race.id)   # car_id -> 晋级次数
    champ = ranking[0]
    # 6 车:3/3 -> 晋级4 -> 决赛组4。冠军至少晋级 1 次(从首轮),且 ≥ 末位
    assert adv[champ] >= 1
    ach = racestats.car_achievements(session, race.id)    # car_id -> {champion,finalist}
    assert ach[champ]["champion"] is True
    assert ach[champ]["finalist"] is True
    # 决赛圈应有 3-4 车 finalist
    assert sum(1 for v in ach.values() if v["finalist"]) in (3, 4)
