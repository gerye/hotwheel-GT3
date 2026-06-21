from __future__ import annotations

from sqlmodel import select
from app.models import Car, CarSeasonMMR
from app.enums import Category
from app.services import seasons as ssvc, cars as csvc
from app.config import INITIAL_MMR


def test_end_season_snapshots_and_resets_mmr(session):
    s = ssvc.start_season(session, name="2026 S1")
    c = csvc.create_car(session, nickname="车", category=Category.GT3,
                        brand="法拉利", casting="", description="", team_id=None)
    c.season_mmr = 1640.0
    c.historical_mmr = 1655.0
    session.add(c); session.commit()
    ssvc.end_season(session, s.id)
    snap = session.exec(select(CarSeasonMMR).where(
        CarSeasonMMR.season_id == s.id, CarSeasonMMR.car_id == c.id)).one()
    assert snap.mmr == 1640.0
    session.refresh(c)
    assert c.season_mmr == INITIAL_MMR        # 赛季 MMR 重置
    assert c.historical_mmr == 1655.0          # 历史 MMR 不变
