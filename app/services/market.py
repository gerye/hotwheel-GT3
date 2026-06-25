from __future__ import annotations

from typing import Optional
from sqlmodel import Session, select
from app.models import Car, Team, Season
from app.enums import CarStatus, ContractType, SeasonStatus
from app.services import market_snapshot, seasons as ssvc


class MarketError(Exception):
    pass


def reference_season(session: Session) -> Optional[Season]:
    """转会参照赛季:最近一个已结束赛季;无则当前进行中赛季。"""
    ended = session.exec(select(Season).where(Season.status == SeasonStatus.FINISHED)
                         .order_by(Season.id.desc())).first()
    return ended or ssvc.get_active_season(session)


def open_market(session: Session) -> None:
    """开盘:按参照赛季写预算/薪资快照;释放所有短期合同车为自由身。"""
    ref = reference_season(session)
    if ref is not None:
        market_snapshot.snapshot_season(session, ref.id)
    for car in session.exec(select(Car).where(
            Car.contract == ContractType.SHORT)).all():
        car.team_id = None
        car.status = CarStatus.UNSIGNED
        car.contract = None
        session.add(car)
    session.commit()
