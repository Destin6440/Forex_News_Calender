"""Smoke tests for the shared _http helper.

These verify session config (UA, retry, pool) without making real HTTP calls.
End-to-end behavior is covered by the source-level tests that monkeypatch
each module's _http_get wrapper.
"""

from urllib3.util.retry import Retry

from ff_calendar_toolkit import _http


def test_build_session_sets_browser_ua():
    sess = _http.build_session()
    try:
        ua = sess.headers["User-Agent"]
        assert "Mozilla" in ua
        assert "Chrome" in ua
    finally:
        sess.close()


def test_build_session_retry_includes_429_and_5xx():
    sess = _http.build_session(max_retries=3)
    try:
        adapter = sess.get_adapter("https://example.com/")
        retry: Retry = adapter.max_retries
        assert 429 in retry.status_forcelist
        assert 500 in retry.status_forcelist
        assert 503 in retry.status_forcelist
        assert retry.total == 3
        assert retry.respect_retry_after_header is True
    finally:
        sess.close()


def test_build_session_retry_allows_only_get_and_head():
    sess = _http.build_session()
    try:
        adapter = sess.get_adapter("https://example.com/")
        retry: Retry = adapter.max_retries
        assert set(retry.allowed_methods) == {"GET", "HEAD"}
    finally:
        sess.close()


def test_http_get_uses_provided_session(monkeypatch):
    """Confirms http_get reuses an external session (no premature close)."""
    closed_externally = {"flag": False}

    class FakeResp:
        content = b"ok"
        def raise_for_status(self):
            pass

    class FakeSession:
        def __init__(self):
            self.calls = []
        def get(self, url, headers=None, timeout=None):
            self.calls.append((url, headers, timeout))
            return FakeResp()
        def close(self):
            closed_externally["flag"] = True

    sess = FakeSession()
    data = _http.http_get("https://example.com/", session=sess, accept="application/json")
    assert data == b"ok"
    assert sess.calls[0][0] == "https://example.com/"
    assert sess.calls[0][1] == {"Accept": "application/json"}
    assert closed_externally["flag"] is False, "external session must not be closed by http_get"
