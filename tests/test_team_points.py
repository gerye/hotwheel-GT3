from sqlmodel import select
from app.enums import Category, ProLevel, RaceFormat, TeamType
from app.services import (seasons as ssvc, teams as tsvc, cars as csvc,
                          tournament as T, team_points as tp, standings as st)
from app.models import Race, RaceRound, Group, GroupMember, Heat, TeamPointEntry


def _run_solo_4(session):
    s = ssvc.start_season(session, name="S1")
    teams, ids = [], []
    for i in range(4):
        t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name=f"q{i}")
        teams.append(t.id)
        ids.append(csvc.create_car(session, nickname=f"c{i}", category=Category.GT3,
                   brand="B", casting="", description="", team_id=t.id).id)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=ids, seed=1)
    rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).first()
    grp = session.exec(select(Group).where(Group.round_id == rnd.id)).first()
    members = [m.car_id for m in session.exec(select(GroupMember)
               .where(GroupMember.group_id == grp.id)).all()]
    for h in session.exec(select(Heat).where(Heat.group_id == grp.id)).all():
        T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(members)})
    return s, race, teams, ids


def test_solo_champion_team_points(session):
    s, race, teams, ids = _run_solo_4(session)
    result = T.advance_round(session, race.id)          # 4 车直接是决赛组
    assert result.kind == "finished"
    champ_car = result.ranking[0]
    champ_team = session.get(__import__('app.models', fromlist=['Car']).Car, champ_car).team_id
    # 4 车决赛组:无晋级(只有 1 轮),冠军 = 决赛名次1 → +4
    pts = st.team_season_points(session, champ_team, s.id)
    assert pts == 4
    # 第2名队 +2,第3名队 +1,第4名队 0
    second_team = session.get(__import__('app.models', fromlist=['Car']).Car, result.ranking[1]).team_id
    assert st.team_season_points(session, second_team, s.id) == 2
