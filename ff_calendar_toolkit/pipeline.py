"""Repeatable bootstrap, backfill, update, validation and manifest workflow."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from .database import CalendarDatabase, ESSENTIAL
from .ingest import (SourceError, VerificationPageError, parse_archive, parse_html,
                     parse_weekly_json)

ARCHIVE_REPO = "https://huggingface.co/datasets/Ehsanrs2/Forex_Factory_Calendar"
WEEKLY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CALENDAR_URL = "https://www.forexfactory.com/calendar?month={month}"
DATA = Path("data")
CHROME_PROFILE = DATA / "chrome-profile"
INTERACTIVE_WAIT_SECONDS = 10 * 60
# A monthly browser page far below a normal archive month is more likely to be
# filtered/incomplete than genuinely quiet. Keep these deliberately conservative
# policy values named so changes are reviewable and testable.
SPARSE_MONTH_MINIMUM_RATIO = 0.25
CATEGORY_PREVALENCE_THRESHOLD = 0.80
MAJOR_CURRENCIES = frozenset({"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"})


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


class CalendarBrowser:
    """One reusable browser session for monthly retrieval.

    Interactive mode deliberately only waits for a human to satisfy an upstream
    verification control.  It contains no challenge-solving or bypass behavior.
    """

    def __init__(self, interactive: bool = False, driver_factory=None, options_factory=None, sleep=time.sleep,
                 monotonic=time.monotonic, output=print) -> None:
        self.interactive = interactive
        self.driver_factory = driver_factory
        self.options_factory = options_factory
        self.sleep = sleep
        self.monotonic = monotonic
        self.output = output
        self.driver = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def _start(self):
        if self.driver is not None:
            return self.driver
        if self.options_factory is None:
            from selenium.webdriver.chrome.options import Options
            options = Options()
        else:
            options = self.options_factory()
        if not self.interactive:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        if self.interactive:
            CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
            options.add_argument(f"--user-data-dir={CHROME_PROFILE.resolve()}")
        if self.driver_factory is None:
            from selenium import webdriver
            factory = lambda opts: webdriver.Chrome(options=opts)
        else:
            factory = self.driver_factory
        self.driver = factory(options)
        return self.driver

    def retrieve(self, month: date) -> tuple[str, list[dict]]:
        driver = self._start()
        period = month.strftime("%Y-%m")
        url = CALENDAR_URL.format(month=month.strftime("%b.%Y").lower())
        driver.get(url)
        self.sleep(float(os.environ.get("FF_PAGE_WAIT_SECONDS", "3")))
        text = driver.page_source
        try:
            return text, parse_html(text, url, period)
        except VerificationPageError:
            if not self.interactive:
                raise

        # Only a positively identified verification page enters manual recovery.
        # Once detected, transient empty/partially rendered pages are expected while
        # the user completes the control, so poll until valid rows or the deadline.
        self.output(
            "VERIFICATION REQUIRED: Complete the CAPTCHA, Cloudflare, or other "
            "verification manually in the open Chrome window. This program will "
            "not solve or bypass it and will wait up to 10 minutes for calendar rows."
        )
        deadline = self.monotonic() + INTERACTIVE_WAIT_SECONDS
        while True:
            self.sleep(2)
            text = driver.page_source
            try:
                return text, parse_html(text, url, period)
            except SourceError:
                if self.monotonic() >= deadline:
                    raise

    def close(self) -> None:
        if self.driver is not None:
            self.driver.quit()
            self.driver = None


def backfill(db: CalendarDatabase, start: date, end: date, html_directory: Path | None = None,
             interactive_browser: bool = False, browser_handoff: bool = False,
             browser: CalendarBrowser | None = None) -> int:
    total=0
    owned_browser = browser is None
    if browser is None and browser_handoff:
        from .browser_handoff import ChromeHandoff
        browser = ChromeHandoff()
    browser = browser or CalendarBrowser(interactive_browser)
    try:
        for month in month_range(start, end):
            period=month.strftime("%Y-%m")
            imported_count = 0
            print(f"Retrieving month {period}...")
            try:
                saved = html_directory / f"{period}.html" if html_directory else None
                if saved and saved.exists():
                    text=saved.read_text(encoding="utf-8")
                    rows=parse_html(text, saved.resolve().as_uri(), period)
                else:
                    _text, rows=browser.retrieve(month)
                # A completed ordinary month with zero rows is never accepted.
                if not rows: raise SourceError("suspiciously empty calendar month")
                imported_count = len(rows)
                total += db.upsert(rows)
                audit = monthly_completeness_audit(db, candidate_browser_month=period)
                reasons = audit["browser_month_issues"].get(period, [])
                if reasons and month < date.today().replace(day=1):
                    message = "; ".join(reasons)
                    db.mark_period(period, "incomplete", len(rows), message, "calendar_html")
                    raise SourceError(f"calendar page failed completeness audit: {message}")
                db.mark_period(period, "complete", len(rows), source_type="calendar_html")
                print(f"Month {period} complete: {len(rows)} rows")
            except Exception as exc:
                db.mark_period(period, "incomplete", imported_count, error=str(exc), source_type="calendar_html")
                print(f"Month {period} incomplete/error: {exc}", file=sys.stderr)
                raise SourceError(f"month {period} remains incomplete: {exc}") from exc
    finally:
        if owned_browser:
            browser.close()
    return total


def update(db: CalendarDatabase) -> int:
    rows=parse_weekly_json(get(WEEKLY_URL), date.today().strftime("%Y-W%W"))
    return db.upsert(rows)


def monthly_completeness_audit(db: CalendarDatabase, candidate_browser_month: str | None = None) -> dict:
    """Compare completed historical browser pages with complete archive months."""
    source_rows = db.connection.execute(
        "SELECT DISTINCT e.event_key,e.date_et,e.currency,e.impact_color,s.source_type "
        "FROM events e JOIN event_sources s ON s.event_key=e.event_key"
    ).fetchall()
    grouped: dict[str, dict[str, list]] = {}
    for row in source_rows:
        month = row["date_et"][:7]
        bucket = grouped.setdefault(row["source_type"], {}).setdefault(month, [])
        bucket.append(row)

    archive = grouped.get("huggingface_archive", {})
    # The archive's last month may end mid-month; it is not baseline evidence.
    complete_archive_months = sorted(archive)[:-1] if len(archive) > 1 else []
    archive_counts = [len(archive[m]) for m in complete_archive_months]
    archive_currency_counts = [len({r["currency"] for r in archive[m]}) for m in complete_archive_months]
    archive_impact_counts = [len({r["impact_color"] for r in archive[m]}) for m in complete_archive_months]
    currency_prevalence = Counter(
        currency for month in complete_archive_months for currency in {r["currency"] for r in archive[month]}
    )
    impact_prevalence = Counter(
        impact for month in complete_archive_months for impact in {r["impact_color"] for r in archive[month]}
    )
    expected_currencies = sorted(currency for currency, count in currency_prevalence.items()
                                 if currency in MAJOR_CURRENCIES and complete_archive_months
                                 and count / len(complete_archive_months) >= CATEGORY_PREVALENCE_THRESHOLD)
    expected_impacts = sorted(impact for impact, count in impact_prevalence.items()
                              if complete_archive_months
                              and count / len(complete_archive_months) >= CATEGORY_PREVALENCE_THRESHOLD)
    baselines = {
        "archive_complete_month_count": len(complete_archive_months),
        "median_events_per_complete_archive_month": median(archive_counts) if archive_counts else None,
        "median_currencies_per_complete_archive_month": median(archive_currency_counts) if archive_currency_counts else None,
        "median_impacts_per_complete_archive_month": median(archive_impact_counts) if archive_impact_counts else None,
        "sparse_month_minimum_ratio": SPARSE_MONTH_MINIMUM_RATIO,
        "category_prevalence_threshold": CATEGORY_PREVALENCE_THRESHOLD,
        "normally_expected_major_currencies": expected_currencies,
        "normally_expected_impact_colors": expected_impacts,
    }
    issues: dict[str, list[str]] = {}
    historical_cutoff = date.today().replace(day=1).isoformat()[:7]
    completed_browser = {r["period"] for r in db.connection.execute(
        "SELECT period FROM periods WHERE status='complete' AND source_type='calendar_html'"
    ) if r["period"] < historical_cutoff}
    # Audit a just-fetched candidate before allowing its period to become complete.
    if candidate_browser_month and candidate_browser_month < historical_cutoff:
        completed_browser.add(candidate_browser_month)
    for month in sorted(completed_browser):
        records = grouped.get("calendar_html", {}).get(month, [])
        month_issues = []
        event_baseline = baselines["median_events_per_complete_archive_month"]
        if event_baseline and len(records) < event_baseline * SPARSE_MONTH_MINIMUM_RATIO:
            month_issues.append(f"{len(records)} events is below {SPARSE_MONTH_MINIMUM_RATIO:.0%} of archive median {event_baseline:g}")
        present_currencies = {r["currency"] for r in records}
        present_impacts = {r["impact_color"] for r in records}
        missing_currencies = sorted(set(expected_currencies) - present_currencies)
        missing_impacts = sorted(set(expected_impacts) - present_impacts)
        if missing_currencies:
            month_issues.append("missing normally expected major currencies: " + ", ".join(missing_currencies))
        if missing_impacts:
            month_issues.append("missing normally expected impact colors: " + ", ".join(missing_impacts))
        if month_issues:
            issues[month] = month_issues
    return {"completeness_baseline": baselines, "browser_month_issues": issues}


def validate(db: CalendarDatabase, strict: bool = False, write_manifest: bool = True) -> tuple[dict, list[str]]:
    rows=db.rows(); errors=[]
    identity_collisions = db.identity_collisions()
    mixed_collision_count = len(identity_collisions["candidates"])
    ambiguous_collision_count = len(identity_collisions["ambiguous"])
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
    audit=monthly_completeness_audit(db)
    suspicious_sparse=sorted(audit["browser_month_issues"])
    checks=((int(not rows),"empty database"),(duplicates,"duplicate event keys"),(missing_required,"rows missing essential fields"),(malformed,"malformed dates"),
            (bad_impact,"unrecognized impact classifications"),(len(incomplete),"incomplete months"),(len(suspicious),"suspiciously empty completed months"))
    errors += [f"{n} {label}" for n,label in checks if n]
    if strict and missing: errors.append(f"{len(missing)} missing historical months")
    if strict and suspicious_sparse: errors.append(f"{len(suspicious_sparse)} suspiciously sparse or filtered completed browser months")
    if strict and (mixed_collision_count or ambiguous_collision_count):
        errors.append(f"{mixed_collision_count + ambiguous_collision_count} unresolved derived/stable natural-identity collisions")
    sync_state=DATA/"sync_state.json"
    exports=DATA/"exports"; hashes={}
    import hashlib
    for fmt in ("csv","parquet"):
        path=exports/f"forex_factory_calendar_full.{fmt}"
        if path.exists(): hashes[fmt]=hashlib.sha256(path.read_bytes()).hexdigest()
    counts_by_month = Counter(r["date_et"][:7] for r in rows)
    by_month_impact: dict[str, Counter] = {}
    by_month_currency: dict[str, Counter] = {}
    for row in rows:
        month=row["date_et"][:7]
        by_month_impact.setdefault(month,Counter())[row["impact_color"]] += 1
        by_month_currency.setdefault(month,Counter())[row["currency"]] += 1
    source_by_month: dict[str, Counter] = {}
    for row in db.connection.execute(
        "SELECT substr(e.date_et,1,7) month,s.source_type,COUNT(DISTINCT e.event_key) count "
        "FROM events e JOIN event_sources s ON s.event_key=e.event_key GROUP BY month,s.source_type"
    ):
        source_by_month.setdefault(row["month"],Counter())[row["source_type"]] = row["count"]
    manifest={"generated_at":datetime.now(timezone.utc).isoformat(),
      "earliest_event_date":min((r["date_et"] for r in rows),default=None),"latest_event_date":max((r["date_et"] for r in rows),default=None),
      "total_events":len(rows),"counts_by_year":dict(sorted(Counter(r["date_et"][:4] for r in rows).items())),
      "counts_by_currency":dict(sorted(Counter(r["currency"] for r in rows).items())),"counts_by_impact":dict(sorted(Counter(r["impact_color"] for r in rows).items())),
      "event_count_by_month":dict(sorted(counts_by_month.items())),
      "count_by_month_and_impact_color":{m:dict(sorted(c.items())) for m,c in sorted(by_month_impact.items())},
      "count_by_month_and_currency":{m:dict(sorted(c.items())) for m,c in sorted(by_month_currency.items())},
      "source_count_by_month":{m:dict(sorted(c.items())) for m,c in sorted(source_by_month.items())},
      "suspiciously_sparse_completed_months":suspicious_sparse,
      "mixed_derived_stable_identity_collisions": mixed_collision_count,
      "ambiguous_identity_collision_groups": ambiguous_collision_count,
      "identity_collision_examples": [
          {"identity": list(group["identity"]),
           "event_keys": [row["event_key"] for row in group["derived"] + group["stable"]]}
          for group in (identity_collisions["candidates"] + identity_collisions["ambiguous"])[:10]
      ],
      **audit,
      "missing_months":missing,"incomplete_months":incomplete,"duplicate_count":duplicates,"rows_missing_essential_fields":missing_required,
      "malformed_dates":malformed,"last_successful_synchronization":json.loads(sync_state.read_text()).get("completed_at") if sync_state.exists() else None,
      "sources":{"archive":ARCHIVE_REPO,"weekly":WEEKLY_URL,"calendar":CALENDAR_URL},"export_sha256":hashes,"validation_errors":errors}
    if write_manifest: DATA.mkdir(exist_ok=True); (DATA/"dataset_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    return manifest,errors


def sync_months(db: CalendarDatabase, force_refresh_start: date | None = None,
                today: date | None = None) -> list[date]:
    """Build the ordered, de-duplicated monthly retrieval plan for one sync."""
    today = today or date.today()
    current_month = today.replace(day=1)
    next_month = (current_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    completed = {row[0] for row in db.connection.execute(
        "SELECT period FROM periods WHERE status='complete' AND source_type='calendar_html'"
    )}
    archive_latest = db.connection.execute(
        "SELECT MAX(e.date_et) FROM events e JOIN event_sources s ON s.event_key=e.event_key "
        "WHERE s.source_type='huggingface_archive'"
    ).fetchone()[0]
    first_tail = date.fromisoformat(archive_latest).replace(day=1) if archive_latest else date(2025, 4, 1)
    required: set[date] = set()
    for month in month_range(first_tail, next_month):
        if month.strftime("%Y-%m") not in completed:
            required.add(month)
    revision_start = max(date(2025, 4, 8), today - timedelta(days=60))
    required.update(month_range(revision_start, next_month))
    if force_refresh_start:
        required.update(month_range(force_refresh_start, current_month))
    return sorted(required)


def sync(db: CalendarDatabase, archive_file: str | None = None,
         interactive_browser: bool = False, browser_handoff: bool = False,
         force_refresh_start: date | None = None,
         yearly_excel_dir: Path | str | None = None) -> dict:
    bootstrap(db,archive_file)
    # One browser (and therefore one cookie session) is shared by gaps and the
    # revision window. Bootstrap remains idempotent and reuses existing rows.
    if browser_handoff:
        from .browser_handoff import ChromeHandoff
        browser_context = ChromeHandoff()
    else:
        browser_context = CalendarBrowser(interactive_browser)
    with browser_context as browser:
        for month in sync_months(db, force_refresh_start):
            backfill(db, month, month, browser=browser)
    update(db); db.export(("csv","parquet"))
    manifest,errors=validate(db,strict=True)
    if errors: raise SourceError("validation failed: "+"; ".join(errors))
    if yearly_excel_dir is not None:
        from .excel_export import export_yearly_excel
        export_yearly_excel(db, yearly_excel_dir, manifest)
    state={"completed_at":datetime.now(timezone.utc).isoformat(),"latest_event_date":manifest["latest_event_date"]}
    DATA.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile("w",dir=DATA,delete=False) as handle: json.dump(state,handle,indent=2); handle.write("\n"); temp=handle.name
    os.replace(temp,DATA/"sync_state.json")
    return manifest
