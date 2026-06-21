from __future__ import annotations

from sqlmodel import Session, select

from app.config import SOLO_TEAM_POINTS, TEAM_TEAM_POINTS
from app.models import Car, Team, TeamPointEntry


def _add_entry(session: Session, *, season_id: int, team_id: int, points: int,
               source_car_id, race_id, description: str) -> None:
    session.add(TeamPointEntry(season_id=season_id, team_id=team_id, points=points,
                               source_car_id=source_car_id, race_id=race_id,
                               description=description))


def award_solo(session: Session, *, season_id: int, race_id: int,
               ranking: list[int]) -> None:
    """ranking: 车 id 的最终名次列表。前 3 名的车给其车队加分。"""
    for pos, car_id in enumerate(ranking[:3], start=1):
        car = session.get(Car, car_id)
        if car is None or car.team_id is None:
            continue
        pts = SOLO_TEAM_POINTS[pos]
        _add_entry(session, season_id=season_id, team_id=car.team_id, points=pts,
                   source_car_id=car_id, race_id=race_id,
                   description=f"{car.nickname} · 单人锦标赛第 {pos} 名")
    session.commit()


def award_team(session: Session, *, season_id: int, race_id: int,
               ranking: list[int]) -> None:
    """ranking: 车队 id 的最终名次列表。前 3 名车队加分。"""
    for pos, team_id in enumerate(ranking[:3], start=1):
        team = session.get(Team, team_id)
        if team is None:
            continue
        pts = TEAM_TEAM_POINTS[pos]
        _add_entry(session, season_id=season_id, team_id=team_id, points=pts,
                   source_car_id=None, race_id=race_id,
                   description=f"车队 · 车队锦标赛第 {pos} 名")
    session.commit()


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
