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
IMPACT_CLASS_COLORS = {
    "icon--ff-impact-red": "red",
    "icon--ff-impact-ora": "orange",
    "icon--ff-impact-orange": "orange",
    "icon--ff-impact-yel": "yellow",
    "icon--ff-impact-yellow": "yellow",
    "icon--ff-impact-gra": "gray",
    "icon--ff-impact-gray": "gray",
}
BLOCK_MARKERS = (
    "cf-chl-",
    "captcha",
    "verify you are human",
    "attention required",
    "security check",
    "just a moment",
)
VERIFICATION_PAGE_ERROR = "verification/security page received instead of calendar data"
MONTH_DATA_TIME_RE = re.compile(
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+Data",
    re.IGNORECASE,
)


class SourceError(RuntimeError): pass


class VerificationPageError(SourceError):
    """The upstream response is a verification page, not calendar data."""


def normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def month_data_identity_label(value: str) -> str | None:
    """Return the normalized identity suffix only for an exact Month Data label."""
    stripped = value.strip()
    return normalized_name(stripped) if MONTH_DATA_TIME_RE.fullmatch(stripped) else None


def impact(value: str) -> tuple[str, str]:
    raw = (value or "").strip().lower()
    aliases = {"high": "red", "medium": "orange", "med": "orange", "low": "yellow",
               "holiday": "gray", "non-economic": "gray", "non economic": "gray"}
    # Class names are an unordered, whitespace-delimited token set. Match the
    # complete token so abbreviated production names do not turn unrelated
    # classes (or arbitrary words containing "ora", "yel", or "gra") into an
    # impact classification.
    color = next((IMPACT_CLASS_COLORS[token] for token in raw.split()
                  if token in IMPACT_CLASS_COLORS), "")
    if not color and raw in IMPACTS:
        color = raw
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
    raw = value.strip().lower()
    compact = raw.replace(" ", "")
    if (compact in {"allday", "tentative"}
            or re.fullmatch(r"day\s+[1-9]\d*", raw)
            or month_data_identity_label(raw) is not None):
        return None, True
    if not raw:
        return None, False
    for fmt in ("%I:%M%p", "%I%p", "%H:%M"):
        try: return datetime.strptime(compact, fmt).time(), False
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
    # Preserve the established ALL_DAY fallback key for all existing non-clock
    # labels. Only the newly supported Month Data labels need a suffix to keep
    # otherwise identical delayed periods distinct.
    month_data_label = month_data_identity_label(raw_time) if clock is None else None
    time_identity = clock.strftime("%H:%M") if clock else "ALL_DAY"
    if month_data_label:
        time_identity += f":{month_data_label}"
    identity = "|".join((day.isoformat(), time_identity, currency, normalized_name(name)))
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
    CELL_KINDS = ("date", "time", "currency", "impact", "event", "actual", "forecast", "previous")

    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs); cls=attrs.get("class", "")
        if tag=="tr" and ("calendar__row" in cls or "calendar_row" in cls):
            self.row={"attrs":attrs,"cells":{},"recognized_cells":[],"placeholder":False}
        elif self.row is not None and tag=="td":
            classes=set(cls.split())
            if "calendar__cell--blank" in classes:
                self.row["placeholder"] = True
            self.cell=next(
                (kind for kind in self.CELL_KINDS if kind in classes or f"calendar__{kind}" in classes),
                None,
            )
            self.text=[]
            if self.cell:
                self.row["recognized_cells"].append(self.cell)
            if self.cell=="impact":
                # Forex Factory expresses impact through CSS classes, including
                # for cells with no visible text.
                self.row["impact_class"]=cls
        elif self.row is not None and self.cell=="event" and tag=="a" and "url" not in self.row:
            href=attrs.get("href")
            if href:
                self.row["url"]=href
        elif self.row is not None and self.cell=="impact" and cls:
            # Older saved pages put the color class on a child icon. This is
            # classification metadata only; the child never becomes a cell.
            self.row["impact_class"] += " " + cls
    def handle_data(self, data):
        if self.cell: self.text.append(data)
    def handle_endtag(self, tag):
        if self.row is not None and tag=="td":
            if self.cell:
                value=" ".join("".join(self.text).split())
                if value: self.row["cells"][self.cell]=value
            self.cell=None
            self.text=[]
        if tag=="tr" and self.row is not None: self.rows.append(self.row); self.row=None


def parse_html(content: str | bytes, source_url: str = "", period: str = "") -> list[dict]:
    text = content.decode("utf-8", "replace") if isinstance(content, bytes) else content
    parser=_CalendarHTML(); parser.feed(text)
    has_verification_marker = any(marker in text.lower() for marker in BLOCK_MARKERS)
    if not parser.rows:
        if has_verification_marker:
            raise VerificationPageError(VERIFICATION_PAGE_ERROR)
        raise SourceError("page contains no recognizable calendar rows")
    result=[]; current_date=None; current_time=None
    for row_number, item in enumerate(parser.rows, start=1):
        cells=item["cells"]
        if cells.get("date"): current_date=cells["date"]
        # Empty time cells carry only within this date; a new date resets the carry.
        if cells.get("date") and "time" not in cells: current_time=None
        if cells.get("time"): current_time=cells["time"]
        event_name = cells.get("event")
        currency = cells.get("currency")
        if not event_name and not currency:
            continue
        if not event_name or not currency:
            missing = "event name" if not event_name else "currency"
            captured = ", ".join(item["recognized_cells"]) or "none"
            raise SourceError(
                f"calendar row {row_number} captured recognized cells [{captured}] "
                f"and is missing an event name or currency: missing {missing}"
            )
        if not current_date:
            raise SourceError("calendar event row has no date and no preceding date")
        imp=cells.get("impact") or item.get("impact_class", "")
        parsed_date = current_date
        if period and not re.search(r"\d{4}", parsed_date): parsed_date += " " + period[:4]
        raw={**cells, "date":parsed_date, "time":current_time or "all day", "impact":imp,
             "event_id":item["attrs"].get("data-event-id", ""),
             "url":urljoin(source_url, item.get("url", ""))}
        result.append(canonical(raw, "saved_html" if source_url.startswith("file:") else "calendar_html", period))
    if not result:
        if has_verification_marker:
            raise VerificationPageError(VERIFICATION_PAGE_ERROR)
        raise SourceError("calendar rows contained no events")
    return result


def calendar_row_counts(content: str | bytes) -> tuple[int, int, int]:
    """Return (all rows, materialized event rows, virtual blank rows).

    This intentionally uses the same conservative row/cell recognition as
    :func:`parse_html`.  Blank virtualization slots are diagnostics, never
    candidate events, while partially populated event rows still reach
    ``parse_html`` and fail closed.
    """
    text = content.decode("utf-8", "replace") if isinstance(content, bytes) else content
    parser = _CalendarHTML()
    parser.feed(text)
    placeholders = sum(bool(row["placeholder"]) for row in parser.rows)
    materialized = sum(
        bool(row["attrs"].get("data-event-id") or row["cells"].get("event") or row["cells"].get("currency"))
        for row in parser.rows
    )
    return len(parser.rows), materialized, placeholders
