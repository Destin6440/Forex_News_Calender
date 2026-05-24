import json

from ff_calendar_toolkit.sources import bloomberg

GDELT_JSON = json.dumps(
    {
        "articles": [
            {
                "title": "Fed signals pause on rate hikes",
                "url": "https://www.bloomberg.com/news/articles/fed-pause",
                "seendate": "20260523T200000Z",
                "domain": "bloomberg.com",
            },
            {
                "title": "ECB holds rates steady",
                "url": "https://www.bloomberg.com/news/articles/ecb-steady",
                "seendate": "20260523T210000Z",
                "domain": "bloomberg.com",
            },
            {
                "title": "",
                "url": "https://www.bloomberg.com/news/articles/empty",
                "seendate": "20260523T220000Z",
            },
        ]
    }
).encode()

GNEWS_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>forex - Google News</title>
    <item>
      <title>Yen drops on BOJ comments - Bloomberg</title>
      <link>https://news.google.com/articles/yen-drop</link>
      <description>Yen weakens as BOJ governor speaks.</description>
      <pubDate>Fri, 23 May 2026 20:30:00 GMT</pubDate>
    </item>
    <item>
      <title>Dollar steady ahead of CPI - Bloomberg</title>
      <link>https://news.google.com/articles/dollar-cpi</link>
      <pubDate>Fri, 23 May 2026 21:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""


def test_parse_gdelt_maps_and_skips_titleless():
    items = bloomberg._parse_gdelt(GDELT_JSON)
    assert len(items) == 2
    first = items[0]
    assert first.source == "bloomberg"
    assert first.title == "Fed signals pause on rate hikes"
    assert first.url.endswith("fed-pause")
    assert first.published_at.startswith("2026-05-23T20:00:00")


def test_parse_gnews_rss():
    items = bloomberg._parse_gnews_rss(GNEWS_RSS)
    assert len(items) == 2
    assert items[0].title.startswith("Yen drops")
    assert items[0].published_at.startswith("2026-05-23T20:30:00")


def test_gdelt_url_builds_query():
    url = bloomberg._gdelt_url('domain:bloomberg.com ("forex" OR "fed")', max_records=25, timespan="6h")
    assert "format=json" in url
    assert "maxrecords=25" in url
    assert "timespan=6h" in url
    assert "sort=DateDesc" in url


def test_fetch_gdelt_passes_query_and_returns_items(monkeypatch):
    captured = {}

    def fake_get(url, timeout=30):
        captured["url"] = url
        return GDELT_JSON

    monkeypatch.setattr(bloomberg, "_http_get", fake_get)
    items = bloomberg.fetch_gdelt(keywords=("forex", "fed"))
    assert len(items) == 2
    assert "domain%3Abloomberg.com" in captured["url"]
    assert "forex" in captured["url"]
    assert "fed" in captured["url"]


def test_fetch_gdelt_on_error_returns_empty(monkeypatch):
    errors = []

    def fake_get(url, timeout=30):
        raise RuntimeError("net down")

    monkeypatch.setattr(bloomberg, "_http_get", fake_get)
    items = bloomberg.fetch_gdelt(on_error=lambda src, e: errors.append((src, str(e))))
    assert items == []
    assert errors == [("gdelt", "net down")]


def test_fetch_gnews_loops_keywords(monkeypatch):
    calls = []

    def fake_get(url, timeout=30):
        calls.append(url)
        return GNEWS_RSS

    monkeypatch.setattr(bloomberg, "_http_get", fake_get)
    items = bloomberg.fetch_gnews(keywords=("forex", "gold"))
    assert len(calls) == 2
    assert len(items) == 4  # 2 items per query


def test_fetch_all_dedups_by_url(monkeypatch):
    def fake_get(url, timeout=30):
        if "gdelt" in url:
            return GDELT_JSON
        return GNEWS_RSS

    monkeypatch.setattr(bloomberg, "_http_get", fake_get)
    items = bloomberg.fetch_all(keywords=("forex",))
    urls = [i.url for i in items]
    assert len(urls) == len(set(urls))
