from __future__ import annotations

from fastapi.testclient import TestClient
from app.main import app
from app.services import seasons as svc

client = TestClient(app)


def test_seasons_page_lists(engine, session):
    svc.start_season(session, name="2026 S1")
    r = client.get("/seasons")
    assert r.status_code == 200 and "2026 S1" in r.text


def test_start_season_via_post(engine, session):
    r = client.post("/seasons", data={"name": "2026 S1"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert svc.get_active_season(session).name == "2026 S1"


def test_end_season_via_post(engine, session):
    s = svc.start_season(session, name="2026 S1")
    r = client.post(f"/seasons/{s.id}/end", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert svc.get_active_season(session) is None
