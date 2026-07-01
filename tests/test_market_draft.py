from __future__ import annotations

from sqlmodel import select
from app.enums import Category, TeamType, CarStatus
from app.services import seasons as ssvc, teams as tsvc, cars as csvc
from app.services import market, market_draft as md
from app.models import Car, Team, MarketDraft, DraftCarSnapshot


def test_models_exist_and_default():
    d = MarketDraft(reference_season_id=1, tiebreak_seed=7)
    assert d.current_team_id is None
    assert d.locked_team_ids == "" and d.locked_categories == ""
    snap = DraftCarSnapshot(draft_id=1, car_id=1, orig_team_id=None,
                            orig_status=CarStatus.UNSIGNED)
    assert snap.orig_status == CarStatus.UNSIGNED


def test_assign_and_release_primitives(session):
    ssvc.start_season(session, name="S1")
    t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="q")
    c = csvc.create_car(session, nickname="c", category=Category.GT3, brand="X",
                        casting="", description="", team_id=None)
    market.assign_car(session, c, t.id, CarStatus.SHORT)
    session.expire_all()
    c = session.get(Car, c.id)
    assert c.team_id == t.id and c.status == CarStatus.SHORT
    market.release_car(session, c)
    session.expire_all()
    c = session.get(Car, c.id)
    assert c.team_id is None and c.status == CarStatus.UNSIGNED


def _seed_two_teams(session):
    ssvc.start_season(session, name="S1")
    ta = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="A")
    tb = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="B")
    long_a = csvc.create_car(session, nickname="A长", category=Category.GT3, brand="X",
                             casting="", description="", team_id=ta.id, signed_status=CarStatus.LONG)
    short_a = csvc.create_car(session, nickname="A短", category=Category.GT3, brand="X",
                              casting="", description="", team_id=ta.id, signed_status=CarStatus.SHORT)
    return ta, tb, long_a, short_a


def test_open_snapshots_all_and_does_not_release(session):
    ta, tb, long_a, short_a = _seed_two_teams(session)
    d = md.open_draft(session)
    session.expire_all()
    assert session.get(Car, short_a.id).status == CarStatus.SHORT
    snaps = session.exec(select(DraftCarSnapshot).where(
        DraftCarSnapshot.draft_id == d.id)).all()
    assert len(snaps) == 2
    assert md.get_draft(session).id == d.id


def test_reset_restores_from_snapshot(session):
    ta, tb, long_a, short_a = _seed_two_teams(session)
    md.open_draft(session)
    market.release_car(session, session.get(Car, short_a.id))
    md.reset_draft(session)
    session.expire_all()
    c = session.get(Car, short_a.id)
    assert c.team_id == ta.id and c.status == CarStatus.SHORT
    d = md.get_draft(session)
    assert d.locked_team_ids == "" and d.current_team_id is None


def test_queue_orders_by_headroom_then_points(session):
    ssvc.start_season(session, name="S1")
    ta = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="A")
    tb = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="B")
    a = csvc.create_car(session, nickname="a", category=Category.GT3, brand="X",
                        casting="", description="", team_id=ta.id, signed_status=CarStatus.LONG)
    b = csvc.create_car(session, nickname="b", category=Category.GT3, brand="X",
                        casting="", description="", team_id=tb.id, signed_status=CarStatus.LONG)
    a.season_mmr = 1400; b.season_mmr = 1600
    session.add(a); session.add(b); session.commit()
    md.open_draft(session)
    q = md.draft_queue(session)
    assert [row["team"].id for row in q][:2] == [ta.id, tb.id]
    assert all("headroom" in row and "locked" in row for row in q)


def test_enter_team_releases_own_shorts_only(session):
    ssvc.start_season(session, name="S1")
    ta = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="A")
    tb = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="B")
    a_long = csvc.create_car(session, nickname="A长", category=Category.GT3, brand="X",
                             casting="", description="", team_id=ta.id, signed_status=CarStatus.LONG)
    a_short = csvc.create_car(session, nickname="A短", category=Category.F1, brand="X",
                              casting="", description="", team_id=ta.id, signed_status=CarStatus.SHORT)
    b_short = csvc.create_car(session, nickname="B短", category=Category.GT3, brand="X",
                              casting="", description="", team_id=tb.id, signed_status=CarStatus.SHORT)
    md.open_draft(session)
    top = md.draft_queue(session)[0]["team"].id
    md.enter_team(session, top)
    session.expire_all()
    d = md.get_draft(session)
    assert d.current_team_id == top
    if top == ta.id:
        assert session.get(Car, a_short.id).status == CarStatus.UNSIGNED
        assert session.get(Car, a_long.id).status == CarStatus.LONG
        assert session.get(Car, b_short.id).status == CarStatus.SHORT


def test_enter_rejects_when_not_top_or_busy(session):
    import pytest
    ssvc.start_season(session, name="S1")
    ta = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="A")
    tb = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="B")
    csvc.create_car(session, nickname="a", category=Category.GT3, brand="X", casting="",
                    description="", team_id=ta.id, signed_status=CarStatus.LONG)
    md.open_draft(session)
    q = md.draft_queue(session)
    top, other = q[0]["team"].id, q[1]["team"].id
    md.enter_team(session, top)
    with pytest.raises(md.DraftError):
        md.enter_team(session, other)


def test_pool_includes_free_and_other_short_excludes_long(session):
    ssvc.start_season(session, name="S1")
    ta = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="A")
    tb = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name="B")
    free = csvc.create_car(session, nickname="自由", category=Category.GT3, brand="X",
                           casting="", description="", team_id=None)
    b_short = csvc.create_car(session, nickname="B短", category=Category.GT3, brand="X",
                              casting="", description="", team_id=tb.id, signed_status=CarStatus.SHORT)
    b_long = csvc.create_car(session, nickname="B长", category=Category.GT3, brand="X",
                             casting="", description="", team_id=tb.id, signed_status=CarStatus.LONG)
    md.open_draft(session)
    md.enter_team(session, md.draft_queue(session)[0]["team"].id)
    ids = {row["car"].id for row in md.category_pool(session, ta.id, Category.GT3)}
    assert free.id in ids and b_short.id in ids
    assert b_long.id not in ids


def test_pool_factory_brand_lock(session):
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    ok = csvc.create_car(session, nickname="无牌", category=Category.GT3, brand="无",
                         casting="", description="", team_id=None)
    bad = csvc.create_car(session, nickname="保时捷车", category=Category.GT3, brand="保时捷",
                          casting="", description="", team_id=None)
    md.open_draft(session)
    md.enter_team(session, tf.id)
    ids = {row["car"].id for row in md.category_pool(session, tf.id, Category.GT3)}
    assert ok.id in ids and bad.id not in ids


def test_recommendation_shapes(session):
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    lg = csvc.create_car(session, nickname="法长", category=Category.GT3, brand="法拉利",
                         casting="", description="", team_id=tf.id, signed_status=CarStatus.LONG)
    free = csvc.create_car(session, nickname="法自由", category=Category.GT3, brand="法拉利",
                           casting="", description="", team_id=None)
    md.open_draft(session)
    md.enter_team(session, tf.id)
    rec = md.category_recommendation(session, tf.id, Category.GT3)
    assert lg.id in rec["keep"]
    assert rec["can_disband"] is False
    assert free.id in rec["strengthen"]


def _enter_top(session):
    md.open_draft(session)
    tid = md.draft_queue(session)[0]["team"].id
    md.enter_team(session, tid)
    return tid


def test_lock_fills_long_category_to_two(session):
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    lg = csvc.create_car(session, nickname="法长", category=Category.GT3, brand="法拉利",
                         casting="", description="", team_id=tf.id, signed_status=CarStatus.LONG)
    free = csvc.create_car(session, nickname="法自由", category=Category.GT3, brand="法拉利",
                           casting="", description="", team_id=None)
    _enter_top(session)
    md.lock_category(session, tf.id, Category.GT3, [lg.id, free.id])
    session.expire_all()
    assert session.get(Car, free.id).team_id == tf.id
    assert session.get(Car, free.id).status == CarStatus.SHORT
    assert Category.GT3 in md.locked_categories(md.get_draft(session))


def test_lock_auto_injects_long_when_ui_omits_it(session):
    """回归:UI 只提交第 2 槽(长期车不在提交里),服务端自动钉入长期车,锁定成功到 2。"""
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    lg = csvc.create_car(session, nickname="法长", category=Category.GT3, brand="法拉利",
                         casting="", description="", team_id=tf.id, signed_status=CarStatus.LONG)
    free = csvc.create_car(session, nickname="法自由", category=Category.GT3, brand="法拉利",
                           casting="", description="", team_id=None)
    _enter_top(session)
    # 模拟模板:只传第 2 槽(法自由),长期车 lg 不在 slots 里
    md.lock_category(session, tf.id, Category.GT3, [free.id, None])
    session.expire_all()
    assert session.get(Car, lg.id).status == CarStatus.LONG and session.get(Car, lg.id).team_id == tf.id
    assert session.get(Car, free.id).team_id == tf.id
    assert Category.GT3 in md.locked_categories(md.get_draft(session))


def test_lock_long_category_may_stop_at_one_when_no_car(session):
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    lg = csvc.create_car(session, nickname="法长", category=Category.GT3, brand="法拉利",
                         casting="", description="", team_id=tf.id, signed_status=CarStatus.LONG)
    _enter_top(session)
    md.lock_category(session, tf.id, Category.GT3, [lg.id, None])
    assert Category.GT3 in md.locked_categories(md.get_draft(session))


def test_lock_rejects_one_active_when_car_available(session):
    import pytest
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    lg = csvc.create_car(session, nickname="法长", category=Category.GT3, brand="法拉利",
                         casting="", description="", team_id=tf.id, signed_status=CarStatus.LONG)
    csvc.create_car(session, nickname="法自由", category=Category.GT3, brand="法拉利",
                    casting="", description="", team_id=None)
    _enter_top(session)
    with pytest.raises(md.DraftError):
        md.lock_category(session, tf.id, Category.GT3, [lg.id, None])


def test_lock_order_long_first(session):
    import pytest
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    csvc.create_car(session, nickname="法长", category=Category.GT3, brand="法拉利",
                    casting="", description="", team_id=tf.id, signed_status=CarStatus.LONG)
    _enter_top(session)
    with pytest.raises(md.DraftError):
        md.lock_category(session, tf.id, Category.F1, [None, None])


def test_unlock_reverts_to_baseline(session):
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    lg = csvc.create_car(session, nickname="法长", category=Category.GT3, brand="法拉利",
                         casting="", description="", team_id=tf.id, signed_status=CarStatus.LONG)
    free = csvc.create_car(session, nickname="法自由", category=Category.GT3, brand="法拉利",
                           casting="", description="", team_id=None)
    _enter_top(session)
    md.lock_category(session, tf.id, Category.GT3, [lg.id, free.id])
    md.unlock_category(session, tf.id, Category.GT3)
    session.expire_all()
    assert session.get(Car, free.id).team_id is None
    assert session.get(Car, lg.id).status == CarStatus.LONG
    assert Category.GT3 not in md.locked_categories(md.get_draft(session))


def test_confirm_requires_all_three_locked(session):
    import pytest
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    _enter_top(session)
    with pytest.raises(md.DraftError):
        md.confirm_team(session, tf.id)
    for cat in Category:
        md.lock_category(session, tf.id, cat, [None, None])
    md.confirm_team(session, tf.id)
    session.expire_all()
    d = md.get_draft(session)
    assert tf.id in md.locked_team_ids(d) and d.current_team_id is None


def test_full_draft_converges(session):
    ssvc.start_season(session, name="S1")
    tids = []
    for i in range(4):
        if i < 2:
            t = tsvc.create_team(session, type=TeamType.FACTORY, brand=["法拉利", "红牛"][i], name=None)
        else:
            t = tsvc.create_team(session, type=TeamType.INDEPENDENT, brand=None, name=f"独立{i}")
        tids.append(t.id)
        brand = session.get(Team, t.id).brand or "无"
        for cat in Category:
            for k in range(2):
                csvc.create_car(session, nickname=f"T{i}-{cat.value}-{k}", category=cat,
                                brand=brand, casting="", description="", team_id=t.id,
                                signed_status=[CarStatus.LONG, CarStatus.SHORT][k])
    md.open_draft(session)
    guard = 0
    while True:
        guard += 1
        assert guard < 50, "队列未收敛"
        top = md._highest_unlocked(session, md.get_draft(session))
        if top is None:
            break
        md.enter_team(session, top)
        for cat in sorted(Category, key=lambda c: not md._has_long(session, top, c)):
            rec = md.category_recommendation(session, top, cat)
            md.lock_category(session, top, cat, (rec["strengthen"] + [None, None])[:2])
        md.confirm_team(session, top)
    session.expire_all()
    assert md.locked_team_ids(md.get_draft(session)) == set(tids)


from fastapi.testclient import TestClient
from app.main import app

_client = TestClient(app)


def test_routes_open_enter_lock_confirm(engine, session):
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    csvc.create_car(session, nickname="法长", category=Category.GT3, brand="法拉利",
                    casting="", description="", team_id=tf.id, signed_status=CarStatus.LONG)
    assert _client.post("/market/open", follow_redirects=False).status_code in (302, 303)
    assert _client.get("/market").status_code == 200
    _client.post("/market/enter", data={"team_id": tf.id}, follow_redirects=False)
    # 断言真实结果,而非仅重定向码:err 会被路由塞进 Location 查询串
    for cat in ["GT3", "F1", "公路车"]:      # GT3(含长期车)先锁
        r = _client.post("/market/lock", data={"team_id": tf.id, "category": cat,
                         "slot1": "", "slot2": ""}, follow_redirects=False)
        assert "err=" not in r.headers["location"], f"{cat} 锁定失败:{r.headers['location']}"
    # GT3 含 1 长期车,池中无第二辆法拉利 GT3 → 逃生阀锁在 1(长期车仍在队)
    session.expire_all()
    from app.models import Car
    lg = session.exec(select(Car).where(Car.nickname == "法长")).first()
    assert lg.team_id == tf.id and lg.status == CarStatus.LONG
    d = md.get_draft(session)
    assert md.locked_categories(d) == set(Category)
    r = _client.post("/market/confirm", data={"team_id": tf.id}, follow_redirects=False)
    assert "err=" not in r.headers["location"]
    session.expire_all()
    d = md.get_draft(session)
    assert tf.id in md.locked_team_ids(d) and d.current_team_id is None
    assert _client.post("/market/reset", follow_redirects=False).status_code in (302, 303)


def test_lock_nonlong_can_disband_even_with_affordable_pool(session):
    """回归:无长期车的类别永远可锁成 0(整类别不参赛),即使池中有买得起的车。"""
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    # 该队 F1 无车(无长期);池中有 1 辆买得起的法拉利 F1 自由车
    csvc.create_car(session, nickname="法自由F1", category=Category.F1, brand="法拉利",
                    casting="", description="", team_id=None)
    _enter_top(session)
    # F1 无长期车 → 允许直接锁成 0(两空),尽管池里有可签车
    md.lock_category(session, tf.id, Category.F1, [None, None])
    assert Category.F1 in md.locked_categories(md.get_draft(session))
    assert tsvc.active_count(session, tf.id, Category.F1, None) == 0


def test_recommendation_nonlong_collapses_when_cannot_fill_two(session):
    """回归:无长期车类别只有 1 辆可签车时,补强建议退化为空(不给非法的 1 车阵容)。"""
    ssvc.start_season(session, name="S1")
    tf = tsvc.create_team(session, type=TeamType.FACTORY, brand="法拉利", name=None)
    only = csvc.create_car(session, nickname="唯一法F1", category=Category.F1, brand="法拉利",
                           casting="", description="", team_id=None)
    _enter_top(session)
    rec = md.category_recommendation(session, tf.id, Category.F1)
    assert rec["strengthen"] == []            # 凑不满 2 → 建议不参赛,而非非法的 [only]
    # 且该建议可直接锁定(不会被校验拒绝)
    md.lock_category(session, tf.id, Category.F1, (rec["strengthen"] + [None, None])[:2])
    assert Category.F1 in md.locked_categories(md.get_draft(session))
