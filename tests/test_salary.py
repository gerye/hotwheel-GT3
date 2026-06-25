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


from app.services import salary as sal
from app.config import SALARY_BASE


def test_salary_mid_car(session):
    from app.enums import Category
    from app.models import Car
    c = Car(nickname="mid", category=Category.GT3, season_mmr=1500, historical_mmr=1500)
    session.add(c); session.commit(); session.refresh(c)
    # 无比赛、MMR1500、非名宿 → 基础 100
    assert sal.compute_salary(session, c, season_id=1) == SALARY_BASE


def test_salary_below_1500_discount(session):
    from app.enums import Category
    from app.models import Car
    c = Car(nickname="bad", category=Category.GT3, season_mmr=1430, historical_mmr=1430)
    session.add(c); session.commit(); session.refresh(c)
    # 1430:折扣 (1500-1430)*0.5=35 → 100-35=65
    assert sal.compute_salary(session, c, season_id=1) == 65


def test_salary_floor(session):
    from app.enums import Category
    from app.models import Car
    c = Car(nickname="terrible", category=Category.GT3, season_mmr=1200, historical_mmr=1200)
    session.add(c); session.commit(); session.refresh(c)
    # 100 - 150 = -50 → 下限 30
    assert sal.compute_salary(session, c, season_id=1) == 30
