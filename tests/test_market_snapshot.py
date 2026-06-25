from __future__ import annotations

from sqlmodel import select
from app.enums import Category, TeamType
from app.services import seasons as ssvc, teams as tsvc, cars as csvc
from app.services import market_snapshot as ms
from app.models import TeamBudget, CarSalary


def test_snapshot_writes_budget_and_salary(session):
    s = ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    csvc.create_car(session, nickname="c", category=Category.GT3, brand="B",
                    casting="", description="", team_id=t.id)
    ms.snapshot_season(session, s.id)
    assert session.exec(select(TeamBudget).where(TeamBudget.season_id == s.id)).all()
    assert session.exec(select(CarSalary).where(CarSalary.season_id == s.id)).all()
