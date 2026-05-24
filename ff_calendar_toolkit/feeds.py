"""Fetch ForexFactory calendar via the public XML feeds on nfs.faireconomy.media.

Replaces the Selenium-based scraper for bulk calendar data:
- 50x faster, no Chrome/driver, no Cloudflare exposure
- Feeds are FF-sanctioned redistribution (no ToS conflict like www.forexfactory.com)
- Trade-off: rolling 3-week window only (last/this/next), no per-event detail panel,
  source timezone is fixed to US/Eastern (the feed's publishing TZ)
"""

from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Iterable, Literal

from .models import ScrapeContext

FEED_BASE = "https://nfs.faireconomy.media"
FEED_URLS = {
    "last": f"{FEED_BASE}/ff_calendar_lastweek.xml",
    "this": f"{FEED_BASE}/ff_calendar_thisweek.xml",
    "next": f"{FEED_BASE}/ff_calendar_nextweek.xml",
}
SOURCE_TIMEZONE = "US/Eastern"

IMPACT_MAP = {
    "high": "red",
    "medium": "orange",
    "low": "yellow",
    "holiday": "gray",
}

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

Week = Literal["last", "this", "next"]


def _http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/xml,text/xml,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _format_feed_date(date_text: str, time_text: str) -> tuple[str, str]:
    """Convert feed's 'MM-DD-YYYY' + 'h:mmam/pm' into row keys consumed by normalize.

    normalize.extract_date_parts expects 'Day MonAbbr DD' anywhere in the string,
    so emit e.g. 'Wed Jan 15'. Time stays as-is (e.g. '8:30am', 'All Day').
    """
    try:
        dt = datetime.strptime(date_text, "%m-%d-%Y")
        date_for_normalize = dt.strftime("%a %b %d")
    except ValueError:
        date_for_normalize = date_text
    return date_for_normalize, (time_text or "").strip()


def _row_from_event(event_el: ET.Element) -> dict:
    def txt(tag: str) -> str:
        node = event_el.find(tag)
        return (node.text or "").strip() if node is not None and node.text else ""

    title = txt("title")
    country = txt("country")
    raw_date = txt("date")
    raw_time = txt("time")
    impact = txt("impact").lower()
    forecast = txt("forecast")
    previous = txt("previous")

    date_for_normalize, time_text = _format_feed_date(raw_date, raw_time)
    impact_color = IMPACT_MAP.get(impact, impact or "")

    return {
        "date": date_for_normalize,
        "time": time_text,
        "currency": country,
        "impact": impact_color,
        "event": title,
        "detail": "",
        "actual": "",
        "forecast": forecast,
        "previous": previous,
    }


def _parse_feed(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    return [_row_from_event(ev) for ev in root.findall("event")]


def fetch_weeks(weeks: Iterable[Week], on_error=None) -> list[dict]:
    """Fetch one or more week feeds and return rows in feed order (chronological per week).

    `on_error(week, exc)` is invoked when a single feed fails (typically nextweek 404 on
    weekends when the new feed isn't published yet). Other weeks still process.
    """
    seen_keys: set[tuple] = set()
    rows: list[dict] = []
    for week in weeks:
        url = FEED_URLS[week]
        try:
            events = _parse_feed(_http_get(url))
        except Exception as exc:
            if on_error is not None:
                on_error(week, exc)
            continue
        for row in events:
            key = (row["date"], row["time"], row["currency"], row["event"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            rows.append(row)
    return rows


def build_context(
    months_label: str,
    target_timezone: str | None,
) -> ScrapeContext:
    now = datetime.now()
    return ScrapeContext(
        month_param=months_label,
        month_name=now.strftime("%B"),
        month_slug=f"{now.year}-{now.month:02d}",
        year=str(now.year),
        source_timezone=SOURCE_TIMEZONE,
        target_timezone=target_timezone,
        scraped_at=datetime.now(timezone.utc).isoformat(),
    )
