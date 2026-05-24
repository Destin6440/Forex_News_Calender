from ff_calendar_toolkit.feeds import _parse_feed, fetch_weeks

SAMPLE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<weeklyevents>
  <event>
    <title>Core CPI m/m</title>
    <country>USD</country>
    <date>01-15-2026</date>
    <time>8:30am</time>
    <impact>High</impact>
    <forecast>0.3%</forecast>
    <previous>0.2%</previous>
    <url>https://ff/x</url>
  </event>
  <event>
    <title>Bank Holiday</title>
    <country>GBP</country>
    <date>01-16-2026</date>
    <time>All Day</time>
    <impact>Holiday</impact>
    <forecast></forecast>
    <previous></previous>
  </event>
</weeklyevents>"""


def test_parse_feed_maps_fields_and_impact():
    rows = _parse_feed(SAMPLE_XML)
    assert len(rows) == 2
    cpi = rows[0]
    assert cpi["event"] == "Core CPI m/m"
    assert cpi["currency"] == "USD"
    assert cpi["impact"] == "red"
    assert cpi["date"] == "Thu Jan 15"
    assert cpi["time"] == "8:30am"
    assert cpi["forecast"] == "0.3%"
    assert cpi["previous"] == "0.2%"

    holiday = rows[1]
    assert holiday["impact"] == "gray"
    assert holiday["time"] == "All Day"


def test_fetch_weeks_skips_failed_feeds(monkeypatch):
    calls = []

    def fake_http_get(url, timeout=30):
        calls.append(url)
        if "lastweek" in url:
            raise RuntimeError("404")
        return SAMPLE_XML

    import ff_calendar_toolkit.feeds as feeds_mod
    monkeypatch.setattr(feeds_mod, "_http_get", fake_http_get)

    errors = []
    rows = fetch_weeks(["last", "this"], on_error=lambda w, e: errors.append((w, str(e))))

    assert len(rows) == 2
    assert errors == [("last", "404")]
    assert len(calls) == 2


def test_fetch_weeks_dedups_across_feeds(monkeypatch):
    import ff_calendar_toolkit.feeds as feeds_mod
    monkeypatch.setattr(feeds_mod, "_http_get", lambda url, timeout=30: SAMPLE_XML)

    rows = fetch_weeks(["this", "next"])
    # same XML returned for both → dedup should yield 2 not 4
    assert len(rows) == 2
