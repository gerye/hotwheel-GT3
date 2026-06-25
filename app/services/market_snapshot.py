from __future__ import annotations

from sqlmodel import Session, select
from app.models import Team, Car, TeamBudget, CarSalary
from app.services import budget as bud, salary as sal


def snapshot_season(session: Session, season_id: int) -> None:
    """为某赛季写入各队预算、各车薪资快照(转会开盘时调用,可重复:先清后写)。"""
    for row in session.exec(select(TeamBudget).where(TeamBudget.season_id == season_id)).all():
        session.delete(row)
    for row in session.exec(select(CarSalary).where(CarSalary.season_id == season_id)).all():
        session.delete(row)
    session.commit()
    for t in session.exec(select(Team)).all():
        session.add(TeamBudget(season_id=season_id, team_id=t.id,
                    budget=bud.compute_budget(session, t, season_id)))
    for c in session.exec(select(Car)).all():
        session.add(CarSalary(season_id=season_id, car_id=c.id,
                    salary=sal.compute_salary(session, c, season_id)))
    session.commit()
