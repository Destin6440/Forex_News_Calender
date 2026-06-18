from fastapi.testclient import TestClient

import server


def test_root_serves_index_html():
    client = TestClient(server.app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Sigaotes" in resp.text
