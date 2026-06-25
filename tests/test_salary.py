from __future__ import annotations

from app.models import TeamBudget, CarSalary, Car
from app.enums import ContractType


def test_new_tables_and_contract(session):
    from app.enums import Category
    c = Car(nickname="x", category=Category.GT3, contract=ContractType.LONG)
    session.add(c); session.commit(); session.refresh(c)
    assert c.contract == ContractType.LONG
    session.add(TeamBudget(season_id=1, team_id=1, budget=800))
    session.add(CarSalary(season_id=1, car_id=c.id, salary=150))
    session.commit()
