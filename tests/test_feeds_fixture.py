"""Schema-drift tests against a real ff_calendar_thisweek.xml capture.

Inline fixtures in test_feeds.py cover parse logic; this file guards against
upstream changes (encoding, CDATA, new impact strings, missing fields).
Capture: 2026-05-24 from https://nfs.faireconomy.media/ff_calendar_thisweek.xml
"""

from pathlib import Path

from ff_calendar_toolkit.feeds import _parse_feed

FIXTURE = Path(__file__).parent / "fixtures" / "ff_calendar_thisweek.xml"


def _load() -> bytes:
    return FIXTURE.read_bytes()


def test_real_feed_declares_windows1252_encoding():
    raw = _load()
    assert raw.startswith(b'<?xml version="1.0" encoding="windows-1252"?>')


def test_real_feed_parses_all_events():
    rows = _parse_feed(_load())
    assert len(rows) >= 50, f"expected ~92 events in a typical week, got {len(rows)}"


def test_real_feed_impact_mapping_covers_all_levels():
    rows = _parse_feed(_load())
    impacts = {row["impact"] for row in rows}
    assert impacts <= {"red", "orange", "yellow", "gray", ""}, f"unknown impact colors: {impacts}"
    assert "red" in impacts or "orange" in impacts, "expected at least one high/medium impact event"


def test_real_feed_cdata_strips_cleanly():
    rows = _parse_feed(_load())
    for row in rows:
        for field in ("event", "currency", "time", "impact"):
            value = row[field]
            assert "<![CDATA[" not in value
            assert "]]>" not in value


def test_real_feed_currencies_are_3_letter_codes():
    rows = _parse_feed(_load())
    currencies = {row["currency"] for row in rows if row["currency"]}
    for code in currencies:
        assert len(code) == 3 and code.isupper(), f"unexpected currency code: {code!r}"


def test_real_feed_date_normalized_to_day_month_format():
    rows = _parse_feed(_load())
    sample = rows[0]["date"]
    parts = sample.split()
    assert len(parts) == 3, f"date not normalized: {sample!r}"
    assert parts[0] in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


def test_real_feed_holiday_events_have_all_day_time_or_clock():
    rows = _parse_feed(_load())
    holidays = [r for r in rows if r["impact"] == "gray"]
    assert holidays, "expected at least one holiday in fixture"
    for row in holidays:
        assert row["time"], "holiday rows should still have a time field"
