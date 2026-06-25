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


def _add_high_historical_peers(session, category, n=12, historical_mmr=1700):
    """添加 n 辆同类别、历史MMR更高的车,使测试车被挤出前10%(非名宿)。"""
    from app.models import Car
    for i in range(n):
        session.add(Car(nickname=f"peer{i}_{category}", category=category,
                         season_mmr=1500, historical_mmr=historical_mmr))
    session.commit()


def test_salary_mid_car(session):
    from app.enums import Category
    from app.models import Car
    c = Car(nickname="mid", category=Category.GT3, season_mmr=1500, historical_mmr=1400)
    session.add(c); session.commit(); session.refresh(c)
    _add_high_historical_peers(session, Category.GT3)
    # 13 辆同类别,前10%=ceil(13*0.1)=2 辆为高历史MMR的peer,测试车非名宿
    # 无比赛、MMR1500、非名宿 → 基础 100
    assert sal.compute_salary(session, c, season_id=1) == SALARY_BASE


def test_salary_below_1500_discount(session):
    from app.enums import Category
    from app.models import Car
    c = Car(nickname="bad", category=Category.GT3, season_mmr=1430, historical_mmr=1400)
    session.add(c); session.commit(); session.refresh(c)
    _add_high_historical_peers(session, Category.GT3)
    # 1430:折扣 (1500-1430)*0.5=35 → 100-35=65,非名宿
    assert sal.compute_salary(session, c, season_id=1) == 65


def test_salary_floor(session):
    from app.enums import Category
    from app.models import Car
    c = Car(nickname="terrible", category=Category.GT3, season_mmr=1200, historical_mmr=1400)
    session.add(c); session.commit(); session.refresh(c)
    _add_high_historical_peers(session, Category.GT3)
    # 100 - 150 = -50 → 下限 30,非名宿
    assert sal.compute_salary(session, c, season_id=1) == 30


def test_salary_legend_alone_in_category(session):
    from app.enums import Category
    from app.models import Car
    c = Car(nickname="legend", category=Category.GT3, season_mmr=1500, historical_mmr=1500)
    session.add(c); session.commit(); session.refresh(c)
    # 该类别仅此一车 → top max(1, ceil(1*0.1))=1 → 是名宿
    assert sal.is_legend(session, c) is True
    # 基础100 + 名宿100 = 200
    assert sal.compute_salary(session, c, season_id=1) == 200
