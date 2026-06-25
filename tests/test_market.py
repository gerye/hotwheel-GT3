from sqlmodel import select
from app.enums import Category, TeamType, CarStatus, ContractType
from app.services import seasons as ssvc, teams as tsvc, cars as csvc, market
from app.models import Car


def _seed(session):
    s = ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    long_car = csvc.create_car(session, nickname="老将", category=Category.GT3, brand="B",
                               casting="", description="", team_id=t.id,
                               contract=ContractType.LONG)
    short_car = csvc.create_car(session, nickname="临时", category=Category.GT3, brand="B",
                                casting="", description="", team_id=t.id,
                                contract=ContractType.SHORT)
    return s, t, long_car, short_car


def test_open_market_releases_short_keeps_long(session):
    s, t, long_car, short_car = _seed(session)
    ssvc.end_season(session, s.id)          # 先结束赛季,产生 MMR 快照
    market.open_market(session)
    session.expire_all()
    assert session.get(Car, long_car.id).team_id == t.id            # 长期留任
    assert session.get(Car, long_car.id).status == CarStatus.ACTIVE
    assert session.get(Car, short_car.id).team_id is None           # 短期释放
    assert session.get(Car, short_car.id).status == CarStatus.UNSIGNED
    assert session.get(Car, short_car.id).contract is None
