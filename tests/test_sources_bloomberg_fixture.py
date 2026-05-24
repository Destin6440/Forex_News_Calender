"""Schema-drift tests against a real Google News RSS capture.

Inline fixtures in test_sources_bloomberg.py cover parse logic; this file
guards against namespace, encoding, and URL-pattern changes Google may make.
Capture: 2026-05-24 from
    https://news.google.com/rss/search?q=site:bloomberg.com+forex&hl=en-US&gl=US&ceid=US:en
"""

from pathlib import Path

from ff_calendar_toolkit.sources import bloomberg

FIXTURE = Path(__file__).parent / "fixtures" / "gnews_bloomberg_forex_rss.xml"


def _load() -> bytes:
    return FIXTURE.read_bytes()


def test_real_gnews_parses_items():
    items = bloomberg._parse_gnews_rss(_load())
    assert len(items) >= 20, f"expected ~100 items, got {len(items)}"


def test_real_gnews_items_have_source_bloomberg():
    items = bloomberg._parse_gnews_rss(_load())
    assert all(item.source == "bloomberg" for item in items)


def test_real_gnews_urls_are_google_redirect_form():
    """Google News returns base64 redirect URLs, not direct publisher links.
    This is a known characteristic that affects URL-based dedup downstream.
    """
    items = bloomberg._parse_gnews_rss(_load())
    google_url_count = sum(1 for item in items if "news.google.com/rss/articles/" in item.url)
    assert google_url_count >= len(items) // 2, (
        f"expected most URLs to be Google redirects; got {google_url_count}/{len(items)}"
    )


def test_real_gnews_published_at_is_iso8601_utc():
    items = bloomberg._parse_gnews_rss(_load())
    for item in items[:10]:
        assert "T" in item.published_at
        assert item.published_at.endswith("+00:00") or item.published_at.endswith("Z")


def test_real_gnews_titles_have_publisher_suffix():
    """Google News appends ' - <Publisher>' to titles; document this for downstream."""
    items = bloomberg._parse_gnews_rss(_load())
    suffixed = sum(1 for item in items if " - " in item.title)
    assert suffixed >= len(items) // 2, "expected most titles to carry ' - Publisher' suffix"


def test_real_gnews_skips_empty_titles_and_links():
    items = bloomberg._parse_gnews_rss(_load())
    for item in items:
        assert item.title.strip()
        assert item.url.strip()
