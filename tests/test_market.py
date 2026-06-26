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


def test_recommend_does_not_starve_lower_headroom_team(session):
    from app.models import Car
    s = ssvc.start_season(session, name="S1")
    # A队:厂商法拉利,1 现役法拉利 GT3(便宜→余额最高),但无自由法拉利车可补
    ta = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    a = csvc.create_car(session, nickname="法A", category=Category.GT3, brand="法拉利",
                        casting="", description="", team_id=ta.id, contract=ContractType.LONG)
    a.season_mmr = 1400; a.historical_mmr = 1400; session.add(a); session.commit()
    # B队:独立,1 现役 GT3(余额略低)
    tb = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="B队")
    b = csvc.create_car(session, nickname="B1", category=Category.GT3, brand="X",
                        casting="", description="", team_id=tb.id, contract=ContractType.LONG)
    b.season_mmr = 1500; b.historical_mmr = 1450; session.add(b); session.commit()
    # 自由 GT3(保时捷):A 因品牌锁不能签,B 独立能签
    free = csvc.create_car(session, nickname="自由", category=Category.GT3, brand="保时捷",
                           casting="", description="", team_id=None)
    free.season_mmr = 1500; free.historical_mmr = 1600; session.add(free); session.commit()
    market.recommend(session, s.id)
    session.expire_all()
    # A 补不动不应阻塞 B:低余额的 B 队应补到 2
    assert session.get(Car, free.id).team_id == tb.id
    assert market._active_in_category(session, tb.id, Category.GT3) == 2
    assert market._active_in_category(session, ta.id, Category.GT3) == 1
