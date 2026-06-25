from __future__ import annotations

from sqlmodel import Session, select

from app.config import INITIAL_MMR
from app.models import Car, Team, TeamPointEntry
from app.services import team_points


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


def award_race(session: Session, race) -> None:
    team_points.award(session, race)


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
