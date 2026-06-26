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


from app.enums import TeamType
from app.services import salary as sal, budget as bud, teams as tsvc
from app.config import MAX_CARS_PER_CATEGORY


def committed_salary(session: Session, team_id: int, season_id: int) -> int:
    cars = session.exec(select(Car).where(Car.team_id == team_id,
                        Car.status == CarStatus.ACTIVE)).all()
    return sum(sal.compute_salary(session, c, season_id) for c in cars)


def headroom(session: Session, team_id: int, season_id: int) -> int:
    team = session.get(Team, team_id)
    return bud.compute_budget(session, team, season_id) - committed_salary(session, team_id, season_id)


def _active_in_category(session: Session, team_id: int, category) -> int:
    return len(session.exec(select(Car).where(
        Car.team_id == team_id, Car.category == category,
        Car.status == CarStatus.ACTIVE)).all())


def sign(session: Session, car_id: int, team_id: int, season_id: int) -> None:
    car = session.get(Car, car_id)
    team = session.get(Team, team_id)
    if car is None or team is None:
        raise MarketError("赛车或车队不存在")
    if car.team_id is not None:
        raise MarketError(f"{car.nickname} 已属于某车队,请先释放再签约")
    if (team.type == TeamType.FACTORY and not tsvc.is_brandless(car.brand)
            and car.brand != team.brand):
        raise MarketError(f"厂商车队「{team.name}」只能签品牌「{team.brand}」或无品牌的车")
    if _active_in_category(session, team_id, car.category) >= MAX_CARS_PER_CATEGORY:
        raise MarketError(f"{team.name} 在 {car.category.value} 已有 2 个现役")
    price = sal.compute_salary(session, car, season_id)
    if price > headroom(session, team_id, season_id):
        raise MarketError(f"预算不足:{car.nickname} 薪资 {price} > 余额 "
                          f"{headroom(session, team_id, season_id)}")
    car.team_id = team_id
    car.status = CarStatus.ACTIVE
    car.contract = ContractType.SHORT     # 自由市场签下默认短期
    session.add(car); session.commit()


def release(session: Session, car_id: int) -> None:
    car = session.get(Car, car_id)
    if car is None:
        raise MarketError("赛车不存在")
    car.team_id = None
    car.status = CarStatus.UNSIGNED
    car.contract = None
    session.add(car); session.commit()


def _free_agents(session: Session):
    return session.exec(select(Car).where(Car.team_id == None)).all()  # noqa: E711


def _partial_categories(session: Session, team_id: int):
    """该队正好 1 个现役的类别列表。"""
    out = []
    for cat in {c.category for c in session.exec(select(Car).where(
            Car.team_id == team_id, Car.status == CarStatus.ACTIVE)).all()}:
        if _active_in_category(session, team_id, cat) == 1:
            out.append(cat)
    return out


def _team_has_need(session: Session, team_id: int) -> bool:
    return len(_partial_categories(session, team_id)) > 0


def recommend(session: Session, season_id: int) -> None:
    """半自动推荐:每轮取余额最高的队,把它已有 1 现役的类别补到 2;
    某队这轮补不动就把它移出候选(不再阻塞别的队),直到没人能补。"""
    blocked: set[int] = set()
    guard = 0
    while True:
        guard += 1
        if guard > 1000:
            break
        teams = [t for t in session.exec(select(Team)).all()
                 if t.id not in blocked and _team_has_need(session, t.id)]
        if not teams:
            break
        teams.sort(key=lambda t: headroom(session, t.id, season_id), reverse=True)
        team = teams[0]
        signed_any = False
        for cat in _partial_categories(session, team.id):
            # 该类别可签的自由车:品牌匹配 + 买得起,挑赛季末 MMR 最高
            cands = []
            for c in _free_agents(session):
                if c.category != cat:
                    continue
                if (team.type == TeamType.FACTORY
                        and not tsvc.is_brandless(c.brand)
                        and c.brand != team.brand):
                    continue
                if sal.compute_salary(session, c, season_id) <= headroom(session, team.id, season_id):
                    cands.append(c)
            cands.sort(key=lambda c: sal._season_mmr(session, c, season_id), reverse=True)
            if cands:
                try:
                    sign(session, cands[0].id, team.id, season_id)
                    signed_any = True
                except MarketError:
                    pass
        if not signed_any:
            blocked.add(team.id)   # 这轮补不动 → 移出候选,让其它队继续
