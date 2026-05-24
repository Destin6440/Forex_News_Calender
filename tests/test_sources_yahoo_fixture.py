"""Schema-drift tests against a real Yahoo Finance RSS capture.

Inline fixtures in test_sources_yahoo.py cover parse logic; this file guards
against schema changes Yahoo may make.

NOTE: Yahoo aggressively rate-limits (HTTP 429) bursts of feed requests from
a single IP. Observed 2026-05-24: ~5 requests in 5 minutes triggered a block
lasting >1 hour from the originating IP. To capture this fixture:

    curl -A "Mozilla/5.0" \\
      "https://feeds.finance.yahoo.com/rss/2.0/headline?s=EURUSD%3DX&region=US&lang=en-US" \\
      -o tests/fixtures/yahoo_eurusd_rss.xml

Run on a cold/fresh network IP (e.g. mobile hotspot, different VPN exit) and
do not retry on 429 — the block extends with each hit. Wait an hour and try
again on a different network.
"""

from pathlib import Path

import pytest

from ff_calendar_toolkit.sources import yahoo

FIXTURE = Path(__file__).parent / "fixtures" / "yahoo_eurusd_rss.xml"


def _load_or_skip() -> bytes:
    if not FIXTURE.exists() or FIXTURE.stat().st_size < 1000:
        pytest.skip(f"fixture missing or rate-limit-stub: {FIXTURE.name}")
    return FIXTURE.read_bytes()


def test_real_yahoo_parses_items():
    items = yahoo._parse_rss(_load_or_skip(), "EURUSD=X")
    assert len(items) >= 1


def test_real_yahoo_items_have_source_and_ticker():
    items = yahoo._parse_rss(_load_or_skip(), "EURUSD=X")
    assert all(item.source == "yahoo" for item in items)
    assert all(item.tickers == ("EURUSD=X",) for item in items)


def test_real_yahoo_published_at_is_iso8601_utc():
    items = yahoo._parse_rss(_load_or_skip(), "EURUSD=X")
    for item in items[:5]:
        assert "T" in item.published_at
        assert item.published_at.endswith("+00:00") or item.published_at.endswith("Z")


def test_real_yahoo_links_are_absolute_https():
    items = yahoo._parse_rss(_load_or_skip(), "EURUSD=X")
    for item in items:
        assert item.url.startswith("https://"), f"non-https url: {item.url!r}"


def test_real_yahoo_skips_empty_titles_and_links():
    items = yahoo._parse_rss(_load_or_skip(), "EURUSD=X")
    for item in items:
        assert item.title.strip()
        assert item.url.strip()
