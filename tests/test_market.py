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


from app.services import salary as sal, budget as bud


def test_headroom_and_sign(session):
    s, t, long_car, short_car = _seed(session)
    ssvc.end_season(session, s.id)
    market.open_market(session)             # short_car 释放
    ref = market.reference_season(session)
    # 自由市场签回 short_car
    market.sign(session, short_car.id, t.id, ref.id)
    session.expire_all()
    assert session.get(Car, short_car.id).team_id == t.id
    assert session.get(Car, short_car.id).status == CarStatus.ACTIVE
    assert session.get(Car, short_car.id).contract == ContractType.SHORT


def test_sign_blocked_when_category_full(session):
    import pytest
    s = ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    for i in range(2):
        csvc.create_car(session, nickname=f"a{i}", category=Category.GT3, brand="B",
                        casting="", description="", team_id=t.id, contract=ContractType.LONG)
    free = csvc.create_car(session, nickname="free", category=Category.GT3, brand="B",
                           casting="", description="", team_id=None)
    ssvc.end_season(session, s.id)
    market.open_market(session)
    ref = market.reference_season(session)
    with pytest.raises(market.MarketError):
        market.sign(session, free.id, t.id, ref.id)     # 该类别已 2 现役


def test_recommend_fills_partial_category(session):
    s = ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    csvc.create_car(session, nickname="留任", category=Category.GT3, brand="B",
                    casting="", description="", team_id=t.id, contract=ContractType.LONG)
    free = csvc.create_car(session, nickname="自由", category=Category.GT3, brand="B",
                           casting="", description="", team_id=None)
    ssvc.end_season(session, s.id)
    market.open_market(session)
    ref = market.reference_season(session)
    market.recommend(session, ref.id)
    session.expire_all()
    # 该队 GT3 原本 1 现役 → 推荐补到 2,签下自由车
    assert session.get(Car, free.id).team_id == t.id
    assert market._active_in_category(session, t.id, Category.GT3) == 2


from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_market_page_and_actions(engine, session):
    s = ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    csvc.create_car(session, nickname="留任", category=Category.GT3, brand="B",
                    casting="", description="", team_id=t.id, contract=ContractType.LONG)
    csvc.create_car(session, nickname="自由", category=Category.GT3, brand="B",
                    casting="", description="", team_id=None)
    ssvc.end_season(session, s.id)
    assert client.post("/market/open", follow_redirects=False).status_code in (302, 303)
    r = client.get("/market")
    assert r.status_code == 200 and "自由" in r.text and "预算" in r.text
    assert client.post("/market/recommend", follow_redirects=False).status_code in (302, 303)


def test_finalize_redirects_to_seasons(engine, session):
    ssvc.start_season(session, name="S1")
    ssvc.end_season(session, session.exec(select(__import__('app.models', fromlist=['Season']).Season)).first().id)
    client.post("/market/open")
    r = client.post("/market/finalize", follow_redirects=False)
    assert r.status_code in (302, 303) and "/seasons" in r.headers["location"]
