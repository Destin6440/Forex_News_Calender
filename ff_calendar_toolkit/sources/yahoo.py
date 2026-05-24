"""Yahoo Finance news fetcher.

Primary path: per-ticker RSS at feeds.finance.yahoo.com — no auth, no crumb, plain XML.
Fallback path: yfinance (with curl_cffi backend) — used only if explicitly enabled,
since it needs an extra dep and is rate-limited harder than RSS.
"""

from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable

from .._http import http_get
from ..models import NewsItem

RSS_BASE = "https://feeds.finance.yahoo.com/rss/2.0/headline"
SOURCE_NAME = "yahoo"

def _http_get(url: str, timeout: int = 30) -> bytes:
    return http_get(url, timeout=timeout, accept="application/rss+xml,application/xml,*/*")


def _ticker_url(ticker: str, region: str = "US", lang: str = "en-US") -> str:
    params = urllib.parse.urlencode({"s": ticker, "region": region, "lang": lang})
    return f"{RSS_BASE}?{params}"


def _parse_pubdate(text: str) -> str:
    if not text:
        return datetime.now(timezone.utc).isoformat()
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).isoformat()


def _parse_rss(xml_bytes: bytes, ticker: str) -> list[NewsItem]:
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        return []
    items: list[NewsItem] = []
    for item_el in channel.findall("item"):
        title = (item_el.findtext("title") or "").strip()
        link = (item_el.findtext("link") or "").strip()
        if not title or not link:
            continue
        items.append(
            NewsItem(
                source=SOURCE_NAME,
                title=title,
                url=link,
                published_at=_parse_pubdate(item_el.findtext("pubDate") or ""),
                summary=(item_el.findtext("description") or "").strip(),
                tickers=(ticker.upper(),),
            )
        )
    return items


def fetch_rss(tickers: Iterable[str], on_error=None) -> list[NewsItem]:
    """Fetch headline RSS per ticker. `on_error(ticker, exc)` for per-ticker failures."""
    out: list[NewsItem] = []
    for ticker in tickers:
        try:
            xml_bytes = _http_get(_ticker_url(ticker))
            out.extend(_parse_rss(xml_bytes, ticker))
        except Exception as exc:
            if on_error is not None:
                on_error(ticker, exc)
            continue
    return out


def fetch_yfinance(tickers: Iterable[str], on_error=None) -> list[NewsItem]:
    """Fallback path using yfinance Ticker.get_news(). Requires `yfinance` installed.

    Raises ImportError if yfinance missing. Use fetch_rss for the no-dep default.
    """
    try:
        import yfinance as yf  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ImportError("yfinance not installed; pip install yfinance") from exc

    out: list[NewsItem] = []
    for ticker in tickers:
        try:
            raw_items = yf.Ticker(ticker).get_news() or []
        except Exception as exc:
            if on_error is not None:
                on_error(ticker, exc)
            continue
        for raw in raw_items:
            content = raw.get("content") or raw
            title = (content.get("title") or "").strip()
            url = (
                content.get("clickThroughUrl", {}).get("url")
                if isinstance(content.get("clickThroughUrl"), dict)
                else content.get("link")
            ) or ""
            if not title or not url:
                continue
            pub_raw = content.get("pubDate") or content.get("providerPublishTime") or ""
            if isinstance(pub_raw, (int, float)):
                published = datetime.fromtimestamp(pub_raw, tz=timezone.utc).isoformat()
            else:
                published = _parse_pubdate(str(pub_raw))
            out.append(
                NewsItem(
                    source=SOURCE_NAME,
                    title=title,
                    url=url,
                    published_at=published,
                    summary=(content.get("summary") or "").strip(),
                    tickers=(ticker.upper(),),
                )
            )
    return out
