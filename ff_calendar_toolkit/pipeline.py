"""Repeatable bootstrap, backfill, update, validation and manifest workflow."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .database import CalendarDatabase, ESSENTIAL
from .ingest import (SourceError, VerificationPageError, parse_archive, parse_html,
                     parse_weekly_json)

ARCHIVE_REPO = "https://huggingface.co/datasets/Ehsanrs2/Forex_Factory_Calendar"
WEEKLY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CALENDAR_URL = "https://www.forexfactory.com/calendar?month={month}"
DATA = Path("data")
CHROME_PROFILE = DATA / "chrome-profile"
HANDOFF_PROFILE = DATA / "chrome-handoff-profile"
INTERACTIVE_WAIT_SECONDS = 10 * 60
HANDOFF_START_TIMEOUT_SECONDS = 30
ARCHIVE_LAST_DATE = date(2025, 4, 7)


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
    latest_archive_date = max(date.fromisoformat(r["date_et"]) for r in rows)
    for month in sorted({r["date_et"][:7] for r in rows}):
        count=sum(r["date_et"].startswith(month) for r in rows)
        is_partial_tail = month == latest_archive_date.strftime("%Y-%m") and latest_archive_date.day != (
            (latest_archive_date.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        ).day
        db.mark_period(
            month,
            "incomplete" if is_partial_tail else "complete",
            count,
            error=(f"archive ends on {latest_archive_date.isoformat()}" if is_partial_tail else None),
            source_type="huggingface_archive",
        )
    return len(rows)


def repair_existing_partial_archive_period(db: CalendarDatabase) -> bool:
    """Repair databases created before the archive tail was treated as partial."""
    period = ARCHIVE_LAST_DATE.strftime("%Y-%m")
    row = db.connection.execute(
        "SELECT status, source_type, event_count FROM periods WHERE period=?", (period,)
    ).fetchone()
    if not row or row["source_type"] != "huggingface_archive" or row["status"] != "complete":
        return False
    db.mark_period(
        period,
        "incomplete",
        row["event_count"],
        error=f"archive ends on {ARCHIVE_LAST_DATE.isoformat()}",
        source_type="huggingface_archive",
    )
    return True


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


def _chrome_binary() -> str:
    """Return an ordinary Chrome/Chromium executable without starting WebDriver."""
    configured = os.environ.get("FF_CHROME_BINARY")
    candidates = [
        configured,
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise SourceError(
        "Google Chrome was not found; set FF_CHROME_BINARY to the Chrome executable"
    )


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_debugger(port: int, process, timeout: int = HANDOFF_START_TIMEOUT_SECONDS) -> None:
    """Wait for the manually controlled Chrome DevTools endpoint on loopback."""
    deadline = time.monotonic() + timeout
    endpoint = f"http://127.0.0.1:{port}/json/version"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SourceError("ordinary Chrome exited before the handoff was ready")
        try:
            with urllib.request.urlopen(endpoint, timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(0.2)
    raise SourceError("ordinary Chrome did not expose the local handoff endpoint in time")


class ChromeHandoffBrowser:
    """Let a human establish an ordinary Chrome session, then attach to it.

    Chrome is launched directly, not by Selenium.  The user first sees and, when
    necessary, legitimately completes the upstream verification.  WebDriver is
    attached only after the user confirms that real calendar rows are visible.
    No challenge is solved, clicked, hidden, or bypassed by this class.
    """

    def __init__(self, input_fn=input, output=print, sleep=time.sleep,
                 process_factory=subprocess.Popen, driver_factory=None,
                 options_factory=None, debugger_wait=_wait_for_debugger,
                 port_factory=_free_loopback_port, chrome_binary: str | None = None) -> None:
        self.input_fn = input_fn
        self.output = output
        self.sleep = sleep
        self.process_factory = process_factory
        self.driver_factory = driver_factory
        self.options_factory = options_factory
        self.debugger_wait = debugger_wait
        self.port_factory = port_factory
        self.chrome_binary = chrome_binary
        self.process = None
        self.driver = None
        self.port = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def _launch_and_attach(self, url: str) -> None:
        HANDOFF_PROFILE.mkdir(parents=True, exist_ok=True)
        self.port = self.port_factory()
        binary = self.chrome_binary or _chrome_binary()
        command = [
            binary,
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={HANDOFF_PROFILE.resolve()}",
            "--no-first-run",
            "--no-default-browser-check",
            url,
        ]
        self.process = self.process_factory(command)
        self.debugger_wait(self.port, self.process)
        self.output(
            "ORDINARY CHROME HANDOFF: Chrome opened the requested Forex Factory "
            "month. Wait until actual calendar rows are visible. Complete any "
            "verification manually; this program does not solve or bypass it."
        )
        self.input_fn("Return here and press Enter only after calendar rows are visible: ")

        if self.options_factory is None:
            from selenium.webdriver.chrome.options import Options
            options = Options()
        else:
            options = self.options_factory()
        options.add_experimental_option(
            "debuggerAddress", f"127.0.0.1:{self.port}"
        )
        if self.driver_factory is None:
            from selenium import webdriver
            self.driver = webdriver.Chrome(options=options)
        else:
            self.driver = self.driver_factory(options)

    @staticmethod
    def _not_ready(exc: SourceError) -> bool:
        return isinstance(exc, VerificationPageError) or str(exc) in {
            "page contains no recognizable calendar rows",
            "calendar rows contained no events",
        }

    def _confirm_visible_rows(self, url: str, period: str) -> tuple[str, list[dict]]:
        while True:
            text = self.driver.page_source
            try:
                return text, parse_html(text, url, period)
            except SourceError as exc:
                if not self._not_ready(exc):
                    raise
                self.output(
                    f"The {period} calendar rows are not readable yet. Finish any "
                    "verification or wait for the calendar to load in Chrome."
                )
                self.input_fn("Press Enter after the calendar rows are visible: ")

    def retrieve(self, month: date) -> tuple[str, list[dict]]:
        period = month.strftime("%Y-%m")
        url = CALENDAR_URL.format(month=month.strftime("%b.%Y").lower())
        if self.driver is None:
            self._launch_and_attach(url)
            return self._confirm_visible_rows(url, period)

        # Keep one ordinary browser/profile/cookie session and move slowly between
        # months.  If the upstream presents another challenge, control returns to
        # the human instead of attempting automated challenge interaction.
        self.sleep(float(os.environ.get("FF_HANDOFF_DELAY_SECONDS", "5")))
        self.driver.get(url)
        self.sleep(float(os.environ.get("FF_PAGE_WAIT_SECONDS", "3")))
        try:
            text = self.driver.page_source
            return text, parse_html(text, url, period)
        except SourceError as exc:
            if not self._not_ready(exc):
                raise
            self.output(
                f"The {period} page needs your attention. Complete any verification "
                "or wait for the calendar rows to finish loading in Chrome; automatic "
                "backfill will resume afterward."
            )
            self.input_fn("Press Enter after the calendar rows are visible: ")
            return self._confirm_visible_rows(url, period)

    def close(self) -> None:
        if self.driver is not None:
            self.driver.quit()
            self.driver = None
        elif self.process is not None and self.process.poll() is None:
            self.process.terminate()
        self.process = None


def backfill(db: CalendarDatabase, start: date, end: date, html_directory: Path | None = None,
             interactive_browser: bool = False, browser_handoff: bool = False,
             browser: CalendarBrowser | ChromeHandoffBrowser | None = None) -> int:
    total=0
    owned_browser = browser is None
    browser = browser or (
        ChromeHandoffBrowser() if browser_handoff else CalendarBrowser(interactive_browser)
    )
    try:
        for month in month_range(start, end):
            period=month.strftime("%Y-%m")
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
                total += db.upsert(rows); db.mark_period(period, "complete", len(rows), source_type="calendar_html")
                print(f"Month {period} complete: {len(rows)} rows")
            except Exception as exc:
                db.mark_period(period, "incomplete", error=str(exc), source_type="calendar_html")
                print(f"Month {period} incomplete/error: {exc}", file=sys.stderr)
                raise SourceError(f"month {period} remains incomplete: {exc}") from exc
    finally:
        if owned_browser:
            browser.close()
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


def sync(db: CalendarDatabase, archive_file: str | None = None,
         interactive_browser: bool = False, browser_handoff: bool = False) -> dict:
    bootstrap(db,archive_file)
    repair_existing_partial_archive_period(db)
    next_month=(date.today().replace(day=28)+timedelta(days=4)).replace(day=1)
    # One browser (and therefore one cookie session) is shared by gaps and the
    # revision window. Bootstrap remains idempotent and reuses existing rows.
    browser_context = (
        ChromeHandoffBrowser() if browser_handoff else CalendarBrowser(interactive_browser)
    )
    with browser_context as browser:
        # Explicitly detect gaps after the archive. Failed periods are absent/incomplete and retried.
        covered={r[0] for r in db.connection.execute("SELECT period FROM periods WHERE status='complete'")}
        for month in month_range(date(2025,4,1),next_month):
            if month.strftime("%Y-%m") not in covered:
                backfill(db,month,month,browser=browser)
        start=max(date(2025,4,8), date.today()-timedelta(days=60))
        # Re-fetch the revision window, current month and next month. A failure prevents state advancement.
        backfill(db,start,next_month,browser=browser)
    update(db); db.export(("csv","parquet"))
    manifest,errors=validate(db,strict=True)
    if errors: raise SourceError("validation failed: "+"; ".join(errors))
    state={"completed_at":datetime.now(timezone.utc).isoformat(),"latest_event_date":manifest["latest_event_date"]}
    DATA.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile("w",dir=DATA,delete=False) as handle: json.dump(state,handle,indent=2); handle.write("\n"); temp=handle.name
    os.replace(temp,DATA/"sync_state.json")
    return manifest
