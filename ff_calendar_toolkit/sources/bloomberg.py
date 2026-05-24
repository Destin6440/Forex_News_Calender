"""Bloomberg headline fetcher — via GDELT 2.0 DOC API and Google News RSS.

Direct bloomberg.com scraping is blocked (Akamai+PX, paywall meter, datacenter-IP 403)
and contradicts their ToS. Both paths below return only headlines + URLs, no body —
which is the legal-greylist zone and what a personal alert pipeline actually needs.

- GDELT: free, real-time, indexes Bloomberg articles within ~15min of publication.
- Google News RSS: site-restricted search query, free, near-real-time.
"""

from __future__ import annotations

import json
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable

from .._http import http_get
from ..models import NewsItem

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
GNEWS_RSS_BASE = "https://news.google.com/rss/search"
SOURCE_NAME = "bloomberg"

def _http_get(url: str, timeout: int = 30) -> bytes:
    return http_get(url, timeout=timeout, accept="application/json,application/xml,*/*")


def _parse_iso(dt_str: str) -> str:
    try:
        # GDELT seendate: "20260523T200000Z"
        dt = datetime.strptime(dt_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).isoformat()


def _parse_rfc822(dt_str: str) -> str:
    if not dt_str:
        return datetime.now(timezone.utc).isoformat()
    try:
        dt = parsedate_to_datetime(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).isoformat()


def _gdelt_url(query: str, max_records: int = 50, timespan: str = "1d") -> str:
    params = urllib.parse.urlencode(
        {
            "query": query,
            "mode": "ArtList",
            "maxrecords": max_records,
            "timespan": timespan,
            "format": "json",
            "sort": "DateDesc",
        }
    )
    return f"{GDELT_DOC_API}?{params}"


def _parse_gdelt(json_bytes: bytes) -> list[NewsItem]:
    payload = json.loads(json_bytes.decode("utf-8") or "{}")
    out: list[NewsItem] = []
    for article in payload.get("articles", []) or []:
        title = (article.get("title") or "").strip()
        url = (article.get("url") or "").strip()
        if not title or not url:
            continue
        out.append(
            NewsItem(
                source=SOURCE_NAME,
                title=title,
                url=url,
                published_at=_parse_iso(article.get("seendate") or ""),
                summary="",
            )
        )
    return out


def fetch_gdelt(
    keywords: Iterable[str] = ("forex", "currency", "dollar", "euro", "inflation", "gold"),
    domain: str = "bloomberg.com",
    timespan: str = "1d",
    max_records: int = 50,
    on_error=None,
) -> list[NewsItem]:
    """Search GDELT for recent Bloomberg articles matching any of `keywords`.

    Query semantics: `domain:bloomberg.com (forex OR currency OR fed ...)`.
    """
    or_clause = " OR ".join(f'"{kw}"' for kw in keywords)
    query = f'domain:{domain} ({or_clause})'
    url = _gdelt_url(query, max_records=max_records, timespan=timespan)
    try:
        return _parse_gdelt(_http_get(url))
    except Exception as exc:
        if on_error is not None:
            on_error("gdelt", exc)
        return []


def _gnews_url(query: str, hl: str = "en-US", gl: str = "US", ceid: str = "US:en") -> str:
    params = urllib.parse.urlencode({"q": query, "hl": hl, "gl": gl, "ceid": ceid})
    return f"{GNEWS_RSS_BASE}?{params}"


def _parse_gnews_rss(xml_bytes: bytes) -> list[NewsItem]:
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        return []
    out: list[NewsItem] = []
    for item_el in channel.findall("item"):
        title = (item_el.findtext("title") or "").strip()
        link = (item_el.findtext("link") or "").strip()
        if not title or not link:
            continue
        out.append(
            NewsItem(
                source=SOURCE_NAME,
                title=title,
                url=link,
                published_at=_parse_rfc822(item_el.findtext("pubDate") or ""),
                summary=(item_el.findtext("description") or "").strip(),
            )
        )
    return out


def fetch_gnews(
    keywords: Iterable[str] = ("forex",),
    site: str = "bloomberg.com",
    on_error=None,
) -> list[NewsItem]:
    """One Google News RSS query per keyword, scoped to `site`."""
    out: list[NewsItem] = []
    for keyword in keywords:
        query = f"site:{site} {keyword}"
        try:
            out.extend(_parse_gnews_rss(_http_get(_gnews_url(query))))
        except Exception as exc:
            if on_error is not None:
                on_error(keyword, exc)
            continue
    return out


def fetch_all(
    keywords: Iterable[str] = ("forex", "currency", "dollar", "euro", "inflation", "gold"),
    on_error=None,
) -> list[NewsItem]:
    """Both GDELT and Google News, deduped by URL."""
    seen_urls: set[str] = set()
    out: list[NewsItem] = []
    keywords = tuple(keywords)
    for items in (fetch_gdelt(keywords=keywords, on_error=on_error), fetch_gnews(keywords=keywords, on_error=on_error)):
        for item in items:
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            out.append(item)
    return out
