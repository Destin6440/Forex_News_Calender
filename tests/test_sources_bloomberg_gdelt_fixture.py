"""Schema-drift tests against a real GDELT 2.0 DOC API capture.

Inline fixtures in test_sources_bloomberg.py cover parse logic; this file
guards against schema changes the GDELT API may make (e.g. new fields, tone
attribute renames).

NOTE: GDELT enforces "one request every 5 seconds" globally per IP. If you
need to refresh this fixture, wait at least 30s between attempts. Also note
that GDELT API may be unreachable from some networks (connection timeouts).

Capture: 2026-05-24 from https://api.gdeltproject.org/api/v2/doc/doc
    query='domain:bloomberg.com "forex"' timespan=7d maxrecords=15
"""

from pathlib import Path

import pytest

from ff_calendar_toolkit.sources import bloomberg

FIXTURE = Path(__file__).parent / "fixtures" / "gdelt_bloomberg.json"


def _load_or_skip() -> bytes:
    if not FIXTURE.exists() or FIXTURE.stat().st_size < 200:
        pytest.skip(f"fixture missing or error-stub: {FIXTURE.name}")
    return FIXTURE.read_bytes()


def test_real_gdelt_parses_articles():
    items = bloomberg._parse_gdelt(_load_or_skip())
    assert len(items) >= 1


def test_real_gdelt_items_have_source_bloomberg():
    items = bloomberg._parse_gdelt(_load_or_skip())
    assert all(item.source == "bloomberg" for item in items)


def test_real_gdelt_urls_point_to_bloomberg_domain():
    items = bloomberg._parse_gdelt(_load_or_skip())
    bloomberg_count = sum(1 for item in items if "bloomberg.com" in item.url)
    assert bloomberg_count == len(items), (
        f"all GDELT results scoped to domain:bloomberg.com should be on bloomberg.com; "
        f"got {bloomberg_count}/{len(items)}"
    )


def test_real_gdelt_published_at_is_iso8601_utc():
    items = bloomberg._parse_gdelt(_load_or_skip())
    for item in items[:5]:
        assert "T" in item.published_at
        assert item.published_at.endswith("+00:00") or item.published_at.endswith("Z")


def test_real_gdelt_skips_titleless_articles():
    items = bloomberg._parse_gdelt(_load_or_skip())
    for item in items:
        assert item.title.strip()
        assert item.url.strip()


def test_real_gdelt_urls_may_contain_explicit_port_443():
    """Documents an actual quirk: GDELT sometimes returns URLs with explicit
    `:443` in the scheme (e.g. https://www.bloomberg.com:443/news/...). This
    matters for URL-based dedup — the canonical form (without :443) won't
    match. Downstream dedup keys on normalized title, not URL, so the impact
    is limited, but worth knowing.
    """
    items = bloomberg._parse_gdelt(_load_or_skip())
    # Not asserting this happens — just exercising the parser tolerates it.
    for item in items:
        assert item.url.startswith("http")
