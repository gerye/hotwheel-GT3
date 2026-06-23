from __future__ import annotations

from fastapi.testclient import TestClient
from app.main import app
from app import netutil

client = TestClient(app)


def test_lan_ip_returns_string():
    ip = netutil.lan_ip()
    assert isinstance(ip, str) and ip.count(".") == 3


def test_access_url_format():
    url = netutil.access_url()
    assert url.startswith("http://") and ":" in url.split("//", 1)[1]


def test_qr_png_endpoint(engine):
    r = client.get("/qr.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert len(r.content) > 0


def test_footer_qr_on_pages(engine, session):
    r = client.get("/database")
    assert r.status_code == 200
    assert "/qr.png" in r.text          # 页脚二维码
    assert "扫码访问" in r.text
