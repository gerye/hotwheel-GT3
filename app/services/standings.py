from __future__ import annotations

from sqlmodel import Session, select

from app.config import INITIAL_MMR
from app.models import Car, Team, TeamPointEntry


def reset_season_mmr(session: Session) -> int:
    """把所有赛车的赛季 MMR 恢复为初始值。返回受影响数量。"""
    cars = session.exec(select(Car)).all()
    for c in cars:
        c.season_mmr = INITIAL_MMR
        session.add(c)
    session.commit()
    return len(cars)


def reset_historical_mmr(session: Session) -> int:
    """把所有赛车的历史 MMR 恢复为初始值。返回受影响数量。"""
    cars = session.exec(select(Car)).all()
    for c in cars:
        c.historical_mmr = INITIAL_MMR
        session.add(c)
    session.commit()
    return len(cars)


def _add_entry(session: Session, *, season_id: int, team_id: int, points: int,
               source_car_id, race_id, description: str) -> None:
    session.add(TeamPointEntry(season_id=season_id, team_id=team_id, points=points,
                               source_car_id=source_car_id, race_id=race_id,
                               description=description))


def award_solo(session: Session, *, season_id: int, race_id: int,
               ranking: list[int]) -> None:
    """ranking: 车 id 的最终名次列表。前 3 名的车给其车队加分。

    TODO(Task 3): 临时占位,新规则见 app/services/team_points.py。
    """
    pass


def award_team(session: Session, *, season_id: int, race_id: int,
               ranking: list[int]) -> None:
    """ranking: 车队 id 的最终名次列表。前 3 名车队加分。

    TODO(Task 3): 临时占位,新规则见 app/services/team_points.py。
    """
    pass


def team_season_points(session: Session, team_id: int, season_id: int) -> int:
    rows = session.exec(select(TeamPointEntry).where(
        TeamPointEntry.team_id == team_id,
        TeamPointEntry.season_id == season_id)).all()
    return sum(r.points for r in rows)


def team_point_sources(session: Session, team_id: int,
                       season_id: int) -> list[TeamPointEntry]:
    return list(session.exec(select(TeamPointEntry).where(
        TeamPointEntry.team_id == team_id,
        TeamPointEntry.season_id == season_id)
        .order_by(TeamPointEntry.id)).all())


def team_board(session: Session, season_id: int) -> list[tuple[Team, int]]:
    teams = session.exec(select(Team)).all()
    board = [(t, team_season_points(session, t.id, season_id)) for t in teams]
    board.sort(key=lambda x: x[1], reverse=True)
    return board
