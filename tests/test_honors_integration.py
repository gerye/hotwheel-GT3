from __future__ import annotations

from sqlmodel import select
from app.enums import Category, ProLevel, RaceFormat, TeamType
from app.services import (seasons as ssvc, cars as csvc, teams as tsvc,
                          tournament as T, standings as st)
from app.models import Car, Race, RaceRound, Group, GroupMember, Heat


def _record_all(session, race_id):
    rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race_id)
                       .order_by(RaceRound.number.desc())).first()
    for g in session.exec(select(Group).where(Group.round_id == rnd.id)).all():
        members = [m.car_id for m in session.exec(select(GroupMember)
                   .where(GroupMember.group_id == g.id)).all()]
        for h in session.exec(select(Heat).where(Heat.group_id == g.id)).all():
            T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(members)})


def _pro_solo_4(session):
    s = ssvc.start_season(session, name="2026 S1")
    teams = [tsvc.create_team(session, type=TeamType.FACTORY, brand=b, name=None)
             for b in ["法拉利", "保时捷", "奥迪", "宝马"]]
    ids = []
    for i, t in enumerate(teams):
        c = csvc.create_car(session, nickname=f"车{i}", category=Category.GT3,
                            brand=t.brand, casting="", description="", team_id=t.id)
        ids.append(c.id)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=ids, seed=1)
    return s, race, ids, teams


def test_finish_pro_solo_updates_mmr_and_team_points(session):
    s, race, ids, teams = _pro_solo_4(session)
    _record_all(session, race.id)
    result = T.advance_round(session, race.id)
    assert result.kind == "finished"
    # MMR 改变
    assert session.get(Car, result.ranking[0]).season_mmr > 1500
    # 车队积分(新规则):4 车单一决赛组、无晋级,冠军决赛圈名次1 → +4(单人赛无 ×2)
    champ = session.get(Car, result.ranking[0])
    assert st.team_season_points(session, champ.team_id, s.id) == 4


def test_exhibition_race_does_not_change_mmr_or_points(session):
    s = ssvc.start_season(session, name="2026 S1")
    ids = [csvc.create_car(session, nickname=f"车{i}", category=Category.GT3,
            brand="法拉利", casting="", description="", team_id=None).id
           for i in range(4)]
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.EXHIBITION,
                         format=RaceFormat.SOLO, car_ids=ids, seed=1)
    _record_all(session, race.id)
    T.advance_round(session, race.id)
    assert session.get(Car, ids[0]).season_mmr == 1500
    from app.models import TeamPointEntry
    assert session.exec(select(TeamPointEntry)).all() == []
