import time

from fastapi.testclient import TestClient

import server


def test_root_serves_index_html():
    client = TestClient(server.app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Sigaotes" in resp.text


def test_api_news_returns_list():
    client = TestClient(server.app)
    resp = client.get("/api/news")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_api_news_records_have_expected_shape(monkeypatch):
    sample = [{
        "title": "Federal Funds Rate", "currency": "USD", "impact": "red",
        "source": "ForexFactory", "cat": "FX",
        "scheduledTime": int(time.time() * 1000) + 3_600_000,
    }]
    monkeypatch.setattr(server, "load_dashboard_news", lambda *a, **k: sample)
    client = TestClient(server.app)
    resp = client.get("/api/news")
    assert resp.json() == sample
