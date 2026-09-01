"""Repeatable bootstrap, backfill, update, validation and manifest workflow."""
from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .database import CalendarDatabase, ESSENTIAL
from .ingest import SourceError, parse_archive, parse_html, parse_weekly_json

ARCHIVE_REPO = "https://huggingface.co/datasets/Ehsanrs2/Forex_Factory_Calendar"
WEEKLY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CALENDAR_URL = "https://www.forexfactory.com/calendar?month={month}"
DATA = Path("data")


def get(url: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ff-calendar-toolkit/1.0 (+MIT data tooling)"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read()
            if response.status != 200 or not content: raise SourceError(f"empty/HTTP {response.status} response from {url}")
            return content
    except (urllib.error.URLError, TimeoutError) as exc: raise SourceError(f"source access failed for {url}: {exc}") from exc


def month_range(start: date, end: date):
    current = start.replace(day=1)
    while current <= end.replace(day=1):
        yield current
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)


def bootstrap(db: CalendarDatabase, archive_file: str | None = None) -> int:
    """Import an explicit archive or discover a supported file in the HF repository."""
    if db.connection.execute("SELECT 1 FROM events WHERE source_type='huggingface_archive' LIMIT 1").fetchone(): return 0
    if archive_file:
        path = Path(archive_file); content = path.read_bytes(); filename = path.name
    else:
        # Dataset repositories can change their physical shard names: use the public tree API.
        api = "https://huggingface.co/api/datasets/Ehsanrs2/Forex_Factory_Calendar/tree/main?recursive=true"
        listing = json.loads(get(api))
        files = [x["path"] for x in listing if x.get("type")=="file" and x["path"].lower().endswith((".csv", ".parquet"))]
        if not files: raise SourceError("Hugging Face archive exposes no CSV or Parquet file")
        filename = sorted(files, key=lambda x: (not x.endswith(".parquet"), x))[0]
        content = get(f"{ARCHIVE_REPO}/resolve/main/{filename}")
    rows = parse_archive(content, filename); db.upsert(rows)
    for month in sorted({r["date_et"][:7] for r in rows}):
        count=sum(r["date_et"].startswith(month) for r in rows); db.mark_period(month, "complete", count, source_type="huggingface_archive")
    return len(rows)


def _selenium_month(month: date) -> str:
    """Use the repository's standard Selenium browser; never attempts challenge bypass."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    options=Options(); options.add_argument("--headless=new"); options.add_argument("--no-sandbox"); options.add_argument("--disable-dev-shm-usage")
    driver=webdriver.Chrome(options=options)
    try:
        driver.get(CALENDAR_URL.format(month=month.strftime("%b.%Y").lower()))
        import time; time.sleep(float(os.environ.get("FF_PAGE_WAIT_SECONDS", "3")))
        return driver.page_source
    finally: driver.quit()


def backfill(db: CalendarDatabase, start: date, end: date, html_directory: Path | None = None) -> int:
    total=0
    for month in month_range(start, end):
        period=month.strftime("%Y-%m")
        try:
            saved = html_directory / f"{period}.html" if html_directory else None
            text=saved.read_text(encoding="utf-8") if saved and saved.exists() else _selenium_month(month)
            rows=parse_html(text, (saved.as_uri() if saved else CALENDAR_URL.format(month=month.strftime("%b.%Y").lower())), period)
            # A completed ordinary month with zero rows is never accepted.
            if not rows: raise SourceError("suspiciously empty calendar month")
            total += db.upsert(rows); db.mark_period(period, "complete", len(rows), source_type="calendar_html")
        except Exception as exc:
            db.mark_period(period, "incomplete", error=str(exc), source_type="calendar_html")
            raise SourceError(f"month {period} remains incomplete: {exc}") from exc
    return total


def update(db: CalendarDatabase) -> int:
    rows=parse_weekly_json(get(WEEKLY_URL), date.today().strftime("%Y-W%W"))
    return db.upsert(rows)


def validate(db: CalendarDatabase, strict: bool = False, write_manifest: bool = True) -> tuple[dict, list[str]]:
    rows=db.rows(); errors=[]
    duplicates=db.connection.execute("SELECT COUNT(*) FROM (SELECT event_key FROM events GROUP BY event_key HAVING COUNT(*)>1)").fetchone()[0]
    missing_required=sum(any(r.get(field) in {None,""} for field in ESSENTIAL) for r in rows)
    malformed=0
    for row in rows:
        try: date.fromisoformat(row["date_et"])
        except (ValueError, TypeError): malformed += 1
    bad_impact=sum(r["impact_color"] not in {"red","orange","yellow","gray"} for r in rows)
    periods={r["period"]:dict(r) for r in db.connection.execute("SELECT * FROM periods")}
    incomplete=sorted(k for k,v in periods.items() if v["status"]!="complete")
    covered={r["date_et"][:7] for r in rows if r.get("date_et")}
    # The declared archive begins in January 2007; absence of all data must not validate.
    missing=[m.strftime("%Y-%m") for m in month_range(date(2007,1,1),date.today()) if m.strftime("%Y-%m") not in covered]
    suspicious=sorted(k for k,v in periods.items() if v["status"]=="complete" and v["event_count"]==0)
    checks=((int(not rows),"empty database"),(duplicates,"duplicate event keys"),(missing_required,"rows missing essential fields"),(malformed,"malformed dates"),
            (bad_impact,"unrecognized impact classifications"),(len(incomplete),"incomplete months"),(len(suspicious),"suspiciously empty completed months"))
    errors += [f"{n} {label}" for n,label in checks if n]
    if strict and missing: errors.append(f"{len(missing)} missing historical months")
    sync_state=DATA/"sync_state.json"
    exports=DATA/"exports"; hashes={}
    import hashlib
    for fmt in ("csv","parquet"):
        path=exports/f"forex_factory_calendar_full.{fmt}"
        if path.exists(): hashes[fmt]=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest={"earliest_event_date":min((r["date_et"] for r in rows),default=None),"latest_event_date":max((r["date_et"] for r in rows),default=None),
      "total_events":len(rows),"counts_by_year":dict(sorted(Counter(r["date_et"][:4] for r in rows).items())),
      "counts_by_currency":dict(sorted(Counter(r["currency"] for r in rows).items())),"counts_by_impact":dict(sorted(Counter(r["impact_color"] for r in rows).items())),
      "missing_months":missing,"incomplete_months":incomplete,"duplicate_count":duplicates,"rows_missing_essential_fields":missing_required,
      "malformed_dates":malformed,"last_successful_synchronization":json.loads(sync_state.read_text()).get("completed_at") if sync_state.exists() else None,
      "sources":{"archive":ARCHIVE_REPO,"weekly":WEEKLY_URL,"calendar":CALENDAR_URL},"export_sha256":hashes,"validation_errors":errors}
    if write_manifest: DATA.mkdir(exist_ok=True); (DATA/"dataset_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    return manifest,errors


def sync(db: CalendarDatabase, archive_file: str | None = None) -> dict:
    bootstrap(db,archive_file)
    next_month=(date.today().replace(day=28)+timedelta(days=4)).replace(day=1)
    # Explicitly detect gaps after the archive. Failed periods are absent/incomplete and retried.
    covered={r[0] for r in db.connection.execute("SELECT period FROM periods WHERE status='complete'")}
    for month in month_range(date(2025,4,1),next_month):
        if month.strftime("%Y-%m") not in covered:
            backfill(db,month,month)
    start=max(date(2025,4,8), date.today()-timedelta(days=60))
    # Re-fetch the revision window, current month and next month. A failure prevents state advancement.
    backfill(db,start,next_month); update(db); db.export(("csv","parquet"))
    manifest,errors=validate(db,strict=True)
    if errors: raise SourceError("validation failed: "+"; ".join(errors))
    state={"completed_at":datetime.now(timezone.utc).isoformat(),"latest_event_date":manifest["latest_event_date"]}
    DATA.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile("w",dir=DATA,delete=False) as handle: json.dump(state,handle,indent=2); handle.write("\n"); temp=handle.name
    os.replace(temp,DATA/"sync_state.json")
    return manifest
