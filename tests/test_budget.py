from sqlmodel import select
from app.enums import Category, ProLevel, RaceFormat, TeamType
from app.services import (seasons as ssvc, teams as tsvc, cars as csvc,
                          tournament as T, standings as st, budget as bud)
from app.models import Race, RaceRound, Group, GroupMember, Heat, Car
from app.config import BUDGET_BASE


def test_budget_base_for_no_history(session):
    s = ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    assert bud.compute_budget(session, t, s.id) == BUDGET_BASE


def test_budget_with_points_and_solo_champion(session):
    s = ssvc.start_season(session, name="S1")
    teams, ids = [], []
    for i in range(4):
        t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name=f"q{i}")
        teams.append(t); ids.append(csvc.create_car(session, nickname=f"c{i}",
            category=Category.GT3, brand="B", casting="", description="", team_id=t.id).id)
    race = T.create_race(session, category=Category.GT3, pro_level=ProLevel.PRO,
                         format=RaceFormat.SOLO, car_ids=ids, seed=1)
    rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race.id)).first()
    grp = session.exec(select(Group).where(Group.round_id == rnd.id)).first()
    members = [m.car_id for m in session.exec(select(GroupMember)
               .where(GroupMember.group_id == grp.id)).all()]
    for h in session.exec(select(Heat).where(Heat.group_id == grp.id)).all():
        T.record_heat(session, h.id, ranks={c: i + 1 for i, c in enumerate(members)})
    res = T.advance_round(session, race.id)
    champ_team_id = session.get(Car, res.ranking[0]).team_id
    champ_team = session.get(__import__('app.models', fromlist=['Team']).Team, champ_team_id)
    # 冠军队:积分4 → 800 + 20*4 + 50(单人冠军) = 930
    assert bud.compute_budget(session, champ_team, s.id) == 800 + 80 + 50
