from __future__ import annotations

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_home_redirects_to_database(engine):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "/database" in r.headers["location"]
