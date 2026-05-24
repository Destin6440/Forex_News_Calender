from ff_calendar_toolkit.sources import yahoo

SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Yahoo! Finance: AAPL</title>
    <link>https://finance.yahoo.com/q/h?s=AAPL</link>
    <item>
      <title>Apple posts record Q4 revenue</title>
      <link>https://finance.yahoo.com/news/apple-q4-record-rev</link>
      <description>Apple reported revenue of $123B.</description>
      <pubDate>Fri, 23 May 2026 20:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Apple announces buyback</title>
      <link>https://finance.yahoo.com/news/apple-buyback</link>
      <description/>
      <pubDate>Fri, 23 May 2026 21:30:00 GMT</pubDate>
    </item>
    <item>
      <title></title>
      <link>https://example.com/empty</link>
      <pubDate>Fri, 23 May 2026 22:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""


def test_parse_rss_maps_fields_and_skips_titleless():
    items = yahoo._parse_rss(SAMPLE_RSS, "AAPL")
    assert len(items) == 2
    first = items[0]
    assert first.source == "yahoo"
    assert first.title == "Apple posts record Q4 revenue"
    assert first.url == "https://finance.yahoo.com/news/apple-q4-record-rev"
    assert first.summary == "Apple reported revenue of $123B."
    assert first.tickers == ("AAPL",)
    assert first.published_at.startswith("2026-05-23T20:00:00")


def test_parse_rss_empty_channel():
    assert yahoo._parse_rss(b"<rss><channel></channel></rss>", "X") == []


def test_fetch_rss_aggregates_across_tickers(monkeypatch):
    captured = []

    def fake_get(url, timeout=30):
        captured.append(url)
        return SAMPLE_RSS

    monkeypatch.setattr(yahoo, "_http_get", fake_get)
    items = yahoo.fetch_rss(["AAPL", "MSFT"])
    assert len(items) == 4
    assert {i.tickers[0] for i in items} == {"AAPL", "MSFT"}
    assert all("s=AAPL" in u or "s=MSFT" in u for u in captured)


def test_fetch_rss_calls_on_error_and_continues(monkeypatch):
    def fake_get(url, timeout=30):
        if "BROKE" in url:
            raise RuntimeError("boom")
        return SAMPLE_RSS

    monkeypatch.setattr(yahoo, "_http_get", fake_get)
    errors = []
    items = yahoo.fetch_rss(["BROKE", "MSFT"], on_error=lambda t, e: errors.append((t, str(e))))
    assert errors == [("BROKE", "boom")]
    assert len(items) == 2
    assert items[0].tickers == ("MSFT",)


def test_ticker_url_encodes_params():
    url = yahoo._ticker_url("USDJPY=X")
    assert "s=USDJPY%3DX" in url
    assert "region=US" in url
    assert "lang=en-US" in url
