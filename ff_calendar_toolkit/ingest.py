"""Source parsing and canonical event normalization."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, time, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
IMPACTS = {"red": "High", "orange": "Medium", "yellow": "Low", "gray": "Non-Economic/Holiday"}
BLOCK_MARKERS = ("cf-chl-", "captcha", "verify you are human", "attention required", "cloudflare", "security check")
VERIFICATION_PAGE_ERROR = "verification/security page received instead of calendar data"


class SourceError(RuntimeError): pass


class VerificationPageError(SourceError):
    """The upstream response is a verification page, not calendar data."""


def normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def impact(value: str) -> tuple[str, str]:
    raw = (value or "").strip().lower()
    aliases = {"high": "red", "medium": "orange", "med": "orange", "low": "yellow",
               "holiday": "gray", "non-economic": "gray", "non economic": "gray"}
    color = next((c for c in IMPACTS if c in raw), "")
    if not color:
        color = next((mapped for label, mapped in aliases.items() if label in raw), "")
    if not color:
        raise SourceError(f"unrecognized impact classification: {value!r}")
    return color, IMPACTS[color]


def _date(value: str) -> date:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y", "%B %d, %Y", "%a%b %d %Y", "%a %b %d %Y"):
        try: return datetime.strptime(value, fmt).date()
        except ValueError: pass
    try: return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError as exc: raise SourceError(f"malformed date: {value!r}") from exc


def _time(value: str) -> tuple[time | None, bool]:
    raw = value.strip().lower().replace(" ", "")
    if raw in {"", "all day", "allday", "tentative", "day 1", "day 2"}:
        return None, raw not in {""}
    for fmt in ("%I:%M%p", "%I%p", "%H:%M"):
        try: return datetime.strptime(raw, fmt).time(), False
        except ValueError: pass
    raise SourceError(f"malformed time: {value!r}")


def canonical(raw: dict, source_type: str, source_period: str = "") -> dict:
    name = str(raw.get("event_name") or raw.get("event") or raw.get("title") or "").strip()
    currency = str(raw.get("currency") or raw.get("country") or "").strip().upper()
    raw_date = str(raw.get("date_et") or raw.get("date") or "").strip()
    raw_time = str(raw.get("time_et") or raw.get("time") or "").strip()
    # Weekly JSON uses an offset-bearing datetime and therefore must be converted, not relabelled.
    if re.match(r"^\d{4}-\d\d-\d\dT", raw_date) or re.search(r"[+-]\d\d:\d\d$", raw_date):
        instant = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        if instant.tzinfo is None: instant = instant.replace(tzinfo=ET)
        local = instant.astimezone(ET); day, clock, all_day = local.date(), local.time().replace(tzinfo=None), False
    else:
        day = _date(raw_date); clock, all_day = _time(raw_time)
    color, level = impact(str(raw.get("impact_color") or raw.get("impact") or raw.get("raw_impact") or ""))
    if not name or not currency: raise SourceError("event name and currency are required")
    dt_et = datetime.combine(day, clock, ET) if clock else None
    source_id = str(raw.get("source_event_id") or raw.get("event_id") or "").strip() or None
    url = str(raw.get("source_url") or raw.get("url") or "").strip()
    if not source_id and url:
        match = re.search(r"(?:event|id)[=/.-](\d+)", url, re.I); source_id = match.group(1) if match else None
    identity = "|".join((day.isoformat(), clock.strftime("%H:%M") if clock else "ALL_DAY", currency, normalized_name(name)))
    key = f"ff:{source_id}" if source_id else "derived:" + hashlib.sha256(identity.encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    return {
        "event_key": key, "source_event_id": source_id, "event_name": name,
        "event_name_normalized": normalized_name(name), "currency": currency,
        "impact_color": color, "impact_level": level, "date_et": day.isoformat(),
        "time_et": clock.strftime("%H:%M") if clock else None,
        "datetime_et": dt_et.isoformat() if dt_et else None,
        "datetime_utc": dt_et.astimezone(timezone.utc).isoformat() if dt_et else None,
        "all_day": all_day, "actual": raw.get("actual"), "forecast": raw.get("forecast"),
        "previous": raw.get("previous"), "source_url": url, "source_type": source_type,
        "source_period": source_period, "first_seen_at": now, "last_seen_at": now,
        "scraped_at": now, "raw_impact": raw.get("raw_impact") or raw.get("impact"),
        "raw_date": raw_date, "raw_time": raw_time,
    }


def parse_weekly_json(content: bytes, period: str = "") -> list[dict]:
    try: payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise SourceError("malformed weekly JSON") from exc
    if not isinstance(payload, list): raise SourceError("weekly JSON is not an array")
    return [canonical(row, "weekly_json", period) for row in payload]


def parse_archive(content: bytes, filename: str = "archive.csv") -> list[dict]:
    if filename.endswith(".parquet"):
        try:
            import pandas as pd
            rows = pd.read_parquet(io.BytesIO(content)).to_dict("records")
        except Exception as exc: raise SourceError(f"cannot read archive parquet: {exc}") from exc
    else:
        text = content.decode("utf-8-sig"); rows = list(csv.DictReader(io.StringIO(text)))
    aliases = {
        "datetime": "date",
        "event": "event_name",
        "title": "event_name",
        "country": "currency",
    }
    output = []
    for original in rows:
        row = {aliases.get(str(k).strip().lower(), str(k).strip().lower()): v for k, v in original.items()}
        output.append(canonical(row, "huggingface_archive", row.get("date", "")[:7]))
    if not output: raise SourceError("archive contains no events")
    return output


class _CalendarHTML(HTMLParser):
    def __init__(self): super().__init__(); self.rows=[]; self.row=None; self.cell=None; self.text=[]
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs); cls=attrs.get("class", "")
        if tag=="tr" and ("calendar__row" in cls or "calendar_row" in cls): self.row={"attrs":attrs,"cells":{}}
        elif self.row is not None and tag in {"td","span"}:
            kinds=("date","time","currency","impact","event","actual","forecast","previous")
            self.cell=next((k for k in kinds if k in cls), None); self.text=[]
            if self.cell=="impact": self.row["impact_class"]=cls
        elif self.row is not None and tag=="a":
            self.row["url"]=attrs.get("href", "")
    def handle_data(self, data):
        if self.cell: self.text.append(data)
    def handle_endtag(self, tag):
        if self.row is not None and self.cell and tag in {"td","span"}:
            value=" ".join("".join(self.text).split())
            if value: self.row["cells"][self.cell]=value
            self.cell=None
        if tag=="tr" and self.row is not None: self.rows.append(self.row); self.row=None


def parse_html(content: str | bytes, source_url: str = "", period: str = "") -> list[dict]:
    text = content.decode("utf-8", "replace") if isinstance(content, bytes) else content
    lowered=text.lower()
    if any(marker in lowered for marker in BLOCK_MARKERS):
        raise VerificationPageError(VERIFICATION_PAGE_ERROR)
    parser=_CalendarHTML(); parser.feed(text)
    if not parser.rows: raise SourceError("page contains no recognizable calendar rows")
    result=[]; current_date=None; current_time=None
    for item in parser.rows:
        cells=item["cells"]
        if cells.get("date"): current_date=cells["date"]
        if not current_date: continue
        # Empty time cells carry only within this date; a new date resets the carry.
        if cells.get("date") and "time" not in cells: current_time=None
        if cells.get("time"): current_time=cells["time"]
        if not cells.get("event") or not cells.get("currency"): continue
        imp=cells.get("impact") or item.get("impact_class", "")
        parsed_date = current_date
        if period and not re.search(r"\d{4}", parsed_date): parsed_date += " " + period[:4]
        raw={**cells, "date":parsed_date, "time":current_time or "all day", "impact":imp,
             "url":urljoin(source_url, item.get("url", ""))}
        result.append(canonical(raw, "saved_html" if source_url.startswith("file:") else "calendar_html", period))
    if not result: raise SourceError("calendar rows contained no events")
    return result
