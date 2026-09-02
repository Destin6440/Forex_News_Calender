from datetime import date
from pathlib import Path

import pytest

from ff_calendar_toolkit.browser_handoff import ChromeHandoff
from ff_calendar_toolkit.cli import build_parser
from ff_calendar_toolkit.ingest import SourceError, calendar_row_counts, parse_html
from ff_calendar_toolkit.ingest import canonical
from ff_calendar_toolkit.database import CalendarDatabase
from ff_calendar_toolkit.pipeline import backfill


CALENDAR = """<table><tr class="calendar__row">
<td class="calendar__date">Tue Apr 8</td><td class="calendar__time">8:30am</td>
<td class="calendar__currency">USD</td><td class="calendar__impact icon--ff-impact-red"></td>
<td class="calendar__event">Tail Event</td></tr></table>"""
CHALLENGE = "<html><title>Verify you are human</title></html>"


class Response:
    def __enter__(self): return self
    def __exit__(self, *_args): pass
    def read(self): return b"{}"


class Process:
    def __init__(self): self.terminated = False
    def poll(self): return None
    def terminate(self): self.terminated = True
    def wait(self, timeout): return 0


class Options:
    debugger_address = None


class Driver:
    def __init__(self, pages): self.pages = iter(pages); self.current = CALENDAR; self.urls = []; self.quit_count = 0
    def get(self, url): self.urls.append(url); self.current = next(self.pages, self.current)
    @property
    def page_source(self): return self.current
    def quit(self): self.quit_count += 1


def virtual_page(batches, active):
    """Build a production-shaped table, retaining blank virtualization slots."""
    rows = ['<table class="calendar__table">']
    for batch_number, events in enumerate(batches):
        rows.append('<tr class="calendar__row calendar__row--day-breaker">'
                    f'<td class="calendar__date">Tue Apr {8 + batch_number} 2025</td></tr>')
        if batch_number not in active:
            rows.extend('<tr class="calendar__row"><td class="calendar__cell--blank"></td></tr>'
                        for _event in events)
            continue
        for event_id, name, clock in events:
            rows.append(f'''<tr class="calendar__row" data-event-id="{event_id}">
                <td class="calendar__time">{clock}</td><td class="calendar__currency">USD</td>
                <td class="calendar__impact icon--ff-impact-red"></td>
                <td class="calendar__event"><a href="/calendar/{event_id}">{name}</a></td>
                <td class="calendar__actual">1</td><td class="calendar__forecast">2</td>
                <td class="calendar__previous">3</td></tr>''')
    return "".join(rows) + "</table>"


class VirtualDriver:
    def __init__(self, pages, *, challenge_at=None):
        self.pages = pages
        self.position = 0
        self.urls = []
        self.contexts = 1
        self.challenge_at = challenge_at
        self.challenge_cleared = False
        self.challenge_seen = False

    def get(self, url):
        self.urls.append(url)

    def execute_script(self, script, *args):
        if args:
            self.position = int(args[0])
            return True
        return {"top": self.position, "height": 1000, "client": 400}

    @property
    def page_source(self):
        if (self.challenge_at is not None and self.position >= self.challenge_at
                and not self.challenge_cleared and not self.challenge_seen):
            self.challenge_seen = True
            return CHALLENGE
        index = 0 if self.position < 250 else (1 if self.position < 500 else 2)
        return self.pages[index]


class StepClock:
    def __init__(self, step=0.01): self.now = -step; self.step = step
    def __call__(self): self.now += self.step; return self.now


def attached_browser(tmp_path, driver, **kwargs):
    browser = ChromeHandoff(tmp_path / "profile", input_fn=kwargs.pop("input_fn", lambda: None),
        output=kwargs.pop("output", lambda _message: None), ps=lambda: "",
        popen=lambda *_args, **_kwargs: Process(), urlopen=lambda *_args, **_kwargs: Response(),
        driver_factory=lambda _options: driver, options_factory=Options,
        sleep=lambda _seconds: None, monotonic=kwargs.pop("monotonic", StepClock()),
        chrome_path="/fake/Chrome", **kwargs)
    return browser


def test_virtualized_sweep_unions_overlapping_snapshots_and_preserves_context(tmp_path, monkeypatch):
    monkeypatch.setenv("FF_PAGE_WAIT_SECONDS", "0")
    monkeypatch.setenv("FF_HANDOFF_SWEEP_SECONDS", "2")
    batches = [
        [("101", "First", "8:30am"), ("102", "Simultaneous", "")],
        [("103", "Middle", "Day 2"), ("104", "Overlap Boundary", "9:00am")],
        [("105", "Last", "10:00am")],
    ]
    pages = [virtual_page(batches, active) for active in ({0}, {0, 1}, {1, 2})]
    driver = VirtualDriver(pages)
    messages = []
    browser = attached_browser(tmp_path, driver, output=messages.append)
    _html, events = browser.retrieve(date(2025, 4, 1))

    assert [event["source_event_id"] for event in events] == ["101", "102", "103", "104", "105"]
    simultaneous = next(event for event in events if event["source_event_id"] == "102")
    assert simultaneous["date_et"] == "2025-04-08" and simultaneous["time_et"] == "08:30"
    day_two = next(event for event in events if event["source_event_id"] == "103")
    assert day_two["date_et"] == "2025-04-09" and day_two["all_day"] is True
    assert driver.urls == ["https://www.forexfactory.com/calendar?month=apr.2025"]
    assert driver.contexts == 1
    assert any("2 → 4 → 5 events" in message for message in messages)
    browser.close()


def test_challenge_during_sweep_pauses_and_restarts_same_month(tmp_path, monkeypatch):
    monkeypatch.setenv("FF_PAGE_WAIT_SECONDS", "0")
    monkeypatch.setenv("FF_HANDOFF_SWEEP_SECONDS", "2")
    batches = [[("201", "First", "8:30am")], [("202", "Second", "9:00am")], [("203", "Last", "10:00am")]]
    pages = [virtual_page(batches, active) for active in ({0}, {1}, {2})]
    driver = VirtualDriver(pages, challenge_at=260)
    presses = []
    def enter():
        presses.append(True)
        if len(presses) == 2:
            driver.challenge_cleared = True
    browser = attached_browser(tmp_path, driver, input_fn=enter)
    _html, events = browser.retrieve(date(2025, 4, 1))
    assert {event["source_event_id"] for event in events} == {"201", "202", "203"}
    assert len(driver.urls) == 1 and len(presses) == 2 and driver.contexts == 1
    browser.close()


def test_unchanging_partial_virtualized_page_times_out(tmp_path, monkeypatch):
    monkeypatch.setenv("FF_PAGE_WAIT_SECONDS", "0")
    monkeypatch.setenv("FF_HANDOFF_SWEEP_SECONDS", "0.08")
    batches = [[("301", "Only Visible Event", "8:30am")], [("302", "Hidden", "9:00am")]]
    page = virtual_page(batches, {0})
    driver = VirtualDriver([page, page, page])
    browser = attached_browser(tmp_path, driver)
    with pytest.raises(SourceError, match=r"accumulated events=1.*materialized rows=1.*placeholder rows=1.*final scroll position=600"):
        browser.retrieve(date(2025, 4, 1))
    browser.close()


def test_production_snapshot_has_45_events_and_376_non_event_placeholders():
    fixture = Path("tests/fixtures/forex_factory_2025-04-rows.html").read_text()
    assert calendar_row_counts(fixture) == (452, 45, 376)
    events = parse_html(fixture, "https://www.forexfactory.com/calendar?month=apr.2025", "2025-04")
    assert len(events) == 45
    assert all(event["source_event_id"] for event in events)
    assert {color: sum(event["impact_color"] == color for event in events)
            for color in ("orange", "red", "yellow")} == {"orange": 6, "red": 4, "yellow": 35}


def test_production_initial_snapshot_is_not_accepted_as_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("FF_PAGE_WAIT_SECONDS", "0")
    monkeypatch.setenv("FF_HANDOFF_SWEEP_SECONDS", "0.08")
    fixture = Path("tests/fixtures/forex_factory_2025-04-rows.html").read_text()
    driver = VirtualDriver([fixture, fixture, fixture])
    browser = attached_browser(tmp_path, driver)
    with pytest.raises(SourceError, match="accumulated events=45"):
        browser.retrieve(date(2025, 4, 1))
    browser.close()


def test_cli_exposes_browser_handoff():
    parser = build_parser()
    assert parser.parse_args(["sync", "--browser-handoff"]).browser_handoff
    args = parser.parse_args(["backfill", "--start", "2025-04-01", "--end", "today", "--browser-handoff"])
    assert args.browser_handoff


def test_external_chrome_is_localhost_only_and_attach_occurs_after_enter(tmp_path):
    calls = []
    process = Process()
    driver = Driver([CALENDAR, CALENDAR])

    def handoff(): calls.append("enter")
    def attach(options):
        calls.append("attach")
        assert options.debugger_address.startswith("127.0.0.1:")
        return driver
    launched = []
    browser = ChromeHandoff(tmp_path / "profile", input_fn=handoff,
        popen=lambda command, **_kwargs: launched.append(command) or process,
        ps=lambda: "", urlopen=lambda *_args, **_kwargs: Response(),
        driver_factory=attach, options_factory=Options, sleep=lambda _seconds: None,
        chrome_path="/fake/Google Chrome")
    _html, rows = browser.retrieve(date(2025, 4, 1))
    browser.retrieve(date(2025, 5, 1))
    browser.close()

    command = launched[0]
    assert command[0] == "/fake/Google Chrome"
    assert "--remote-debugging-address=127.0.0.1" in command
    assert any(arg == f"--user-data-dir={(tmp_path / 'profile').resolve()}" for arg in command)
    assert calls == ["enter", "attach"]
    assert len(rows) == 1 and len(driver.urls) == 2
    assert process.terminated


def test_handoff_reminds_user_to_clear_calendar_filters(tmp_path):
    messages = []
    browser = ChromeHandoff(tmp_path / "profile", input_fn=lambda: None, output=messages.append,
        ps=lambda: "", popen=lambda *_args, **_kwargs: Process(),
        urlopen=lambda *_args, **_kwargs: Response(), driver_factory=lambda _options: Driver([CALENDAR]),
        options_factory=Options, sleep=lambda _seconds: None, chrome_path="/fake/Chrome")
    browser.retrieve(date(2025, 4, 1))
    assert "Before pressing Enter, make sure Forex Factory is displaying all currencies and all impact levels, with no research-specific calendar filter active." in messages[0]
    browser.close()


def test_existing_dedicated_debug_chrome_is_reused_and_not_terminated(tmp_path):
    profile = (tmp_path / "profile").resolve()
    launched = []
    driver = Driver([CALENDAR])
    class Service:
        stopped = False
        def stop(self): self.stopped = True
    driver.service = Service()
    browser = ChromeHandoff(profile, input_fn=lambda: None,
        popen=lambda *args, **kwargs: launched.append(args),
        ps=lambda: f"42 /Chrome --user-data-dir={profile} --remote-debugging-port=9222",
        urlopen=lambda *_args, **_kwargs: Response(), driver_factory=lambda _options: driver,
        options_factory=Options, sleep=lambda _seconds: None)
    browser.retrieve(date(2025, 4, 1))
    browser.close()
    assert launched == []
    assert browser.launched_by_us is False
    assert driver.quit_count == 0
    assert driver.service.stopped


def test_active_profile_without_debugging_is_never_modified(tmp_path):
    profile = (tmp_path / "profile").resolve(); profile.mkdir()
    lock = profile / "SingletonLock"; lock.write_text("active")
    browser = ChromeHandoff(profile, ps=lambda: f"42 /Chrome --user-data-dir={profile}")
    with pytest.raises(SourceError, match="already in use"):
        browser.start()
    assert lock.read_text() == "active"


def test_stale_singleton_files_removed_only_after_profile_proven_unused(tmp_path):
    profile = tmp_path / "profile"; profile.mkdir()
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        (profile / name).write_text("stale")
    browser = ChromeHandoff(profile, ps=lambda: "", popen=lambda *_args, **_kwargs: Process(),
        urlopen=lambda *_args, **_kwargs: Response(), sleep=lambda _seconds: None,
        chrome_path="/fake/Chrome")
    browser.start()
    assert not any((profile / name).exists() for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"))
    browser.close()


def test_later_challenge_pauses_and_retries_same_month_without_navigation(tmp_path):
    driver = Driver([CALENDAR, CHALLENGE])
    presses = []
    def enter():
        presses.append(True)
        if len(presses) == 2:
            driver.current = CALENDAR
    browser = ChromeHandoff(tmp_path / "profile", input_fn=enter, ps=lambda: "",
        popen=lambda *_args, **_kwargs: Process(), urlopen=lambda *_args, **_kwargs: Response(),
        driver_factory=lambda _options: driver, options_factory=Options,
        sleep=lambda _seconds: None, chrome_path="/fake/Chrome")
    browser.retrieve(date(2025, 4, 1))
    _html, rows = browser.retrieve(date(2025, 5, 1))
    assert len(rows) == 1
    assert len(driver.urls) == 2
    assert len(presses) == 2
    browser.close()


def test_failed_debugger_start_cleans_up_newly_launched_chrome(tmp_path):
    process = Process()
    browser = ChromeHandoff(tmp_path / "profile", ps=lambda: "",
        popen=lambda *_args, **_kwargs: process,
        urlopen=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("not ready")),
        sleep=lambda _seconds: None, chrome_path="/fake/Chrome")
    with pytest.raises(SourceError, match="debugger did not become ready"):
        browser.start()
    assert process.terminated
    assert browser.port is None


def test_owned_cleanup_continues_when_selenium_quit_fails(tmp_path):
    process = Process()
    class BadDriver:
        def quit(self): raise RuntimeError("detach failed")
    messages = []
    browser = ChromeHandoff(tmp_path / "profile", output=messages.append)
    browser.launched_by_us = True
    browser.process = process
    browser.driver = BadDriver()
    browser.close()
    assert process.terminated
    assert any("detach failed" in message for message in messages)


def test_post_enter_empty_page_is_polled_until_rows_render(tmp_path, monkeypatch):
    monkeypatch.setenv("FF_PAGE_WAIT_SECONDS", "0")
    class RenderingDriver(Driver):
        reads = 0
        @property
        def page_source(self):
            self.reads += 1
            return "<html></html>" if self.reads == 1 else CALENDAR
    driver = RenderingDriver([CALENDAR])
    clock = iter((0.0, 0.1, 0.2))
    browser = ChromeHandoff(tmp_path / "profile", input_fn=lambda: None, ps=lambda: "",
        popen=lambda *_args, **_kwargs: Process(), urlopen=lambda *_args, **_kwargs: Response(),
        driver_factory=lambda _options: driver, options_factory=Options,
        sleep=lambda _seconds: None, monotonic=lambda: next(clock), chrome_path="/fake/Chrome")
    _html, rows = browser.retrieve(date(2025, 4, 1))
    assert len(rows) == 1 and driver.reads == 2
    browser.close()


def test_post_enter_malformed_event_row_fails_without_polling(tmp_path, monkeypatch):
    monkeypatch.setenv("FF_PAGE_WAIT_SECONDS", "0")
    malformed = CALENDAR.replace('<td class="calendar__currency">USD</td>', "")
    driver = Driver([malformed])
    browser = ChromeHandoff(tmp_path / "profile", input_fn=lambda: None, ps=lambda: "",
        popen=lambda *_args, **_kwargs: Process(), urlopen=lambda *_args, **_kwargs: Response(),
        driver_factory=lambda _options: driver, options_factory=Options,
        sleep=lambda seconds: None if seconds == 0 else pytest.fail("malformed rows must not be polled"),
        monotonic=lambda: 0, chrome_path="/fake/Chrome")
    with pytest.raises(SourceError, match="missing currency"):
        browser.retrieve(date(2025, 4, 1))
    browser.close()


def test_handoff_profile_is_git_ignored():
    assert "data/chrome-handoff-profile/" in Path(".gitignore").read_text()


def test_completed_month_stays_saved_when_a_later_month_fails(tmp_path):
    class Browser:
        calls = 0
        def retrieve(self, _month):
            self.calls += 1
            if self.calls == 2:
                raise SourceError("later failure")
            return CALENDAR, [canonical({"date": "2025-04-08", "time": "8:30am",
                "currency": "USD", "impact": "red", "event": "Saved Event"},
                "calendar_html", "2025-04")]

    db = CalendarDatabase(tmp_path / "calendar.sqlite")
    with pytest.raises(SourceError, match="2025-05 remains incomplete"):
        backfill(db, date(2025, 4, 1), date(2025, 5, 31), browser=Browser())
    statuses = {row["period"]: row["status"] for row in db.connection.execute("SELECT * FROM periods")}
    assert statuses == {"2025-04": "complete", "2025-05": "incomplete"}
    assert len(db.rows()) == 1
    db.close()


def test_filtered_import_then_forced_full_import_adds_missing_without_duplicates(tmp_path):
    currencies = ("USD", "EUR", "GBP", "JPY")
    impacts = ("red", "orange", "yellow", "gray")
    def records(month, source, count=8):
        return [canonical({"date": f"{month}-{index + 1:02d}", "time": "8:30am",
            "currency": currencies[index % 4], "impact": impacts[index % 4],
            "event": f"Release {month} {index}"}, source, month) for index in range(count)]

    db = CalendarDatabase(tmp_path / "calendar.sqlite")
    for month in ("2024-01", "2024-02", "2024-03"):
        archive = records(month, "huggingface_archive")
        db.upsert(archive); db.mark_period(month, "complete", len(archive), source_type="huggingface_archive")

    full = records("2025-01", "calendar_html")
    class SparseBrowser:
        def retrieve(self, _month): return CALENDAR, full[:1]
    with pytest.raises(SourceError, match="failed completeness audit"):
        backfill(db, date(2025, 1, 1), date(2025, 1, 31), browser=SparseBrowser())
    assert len([row for row in db.rows() if row["date_et"].startswith("2025-01")]) == 1
    assert db.connection.execute("SELECT status FROM periods WHERE period='2025-01'").fetchone()[0] == "incomplete"

    class FullBrowser:
        def retrieve(self, _month): return CALENDAR, full
    assert backfill(db, date(2025, 1, 1), date(2025, 1, 31), browser=FullBrowser()) == 8
    month_rows = [row for row in db.rows() if row["date_et"].startswith("2025-01")]
    assert len(month_rows) == 8
    assert len({row["event_key"] for row in month_rows}) == 8
    assert db.connection.execute("SELECT status FROM periods WHERE period='2025-01'").fetchone()[0] == "complete"
    db.close()


def test_april_archive_monthly_overlap_is_idempotent_and_preserves_first_seen(tmp_path):
    db = CalendarDatabase(tmp_path / "calendar.sqlite")
    archive = canonical({"date": "2025-04-07", "time": "8:30am", "currency": "USD",
                         "impact": "red", "event": "Shared Release"},
                        "huggingface_archive", "2025-04")
    archive["first_seen_at"] = "2025-04-08T00:00:00+00:00"
    monthly = canonical({"date": "2025-04-07", "time": "8:30am", "currency": "USD",
                         "impact": "red", "event": "Shared Release", "event_id": "12345"},
                        "calendar_html", "2025-04")
    db.upsert([archive]); db.upsert([monthly]); db.upsert([monthly])
    rows = db.rows()
    db.close()
    assert len(rows) == 1
    assert rows[0]["source_event_id"] == "12345"
    assert rows[0]["first_seen_at"] == "2025-04-08T00:00:00+00:00"


def test_archive_monthly_repeated_sequence_preserves_all_provenance_and_tail(tmp_path):
    db = CalendarDatabase(tmp_path / "calendar.sqlite")
    archive = canonical({"date": "2025-04-07", "time": "8:30am", "currency": "USD",
                         "impact": "red", "event": "Shared Release"},
                        "huggingface_archive", "2025-04")
    archive["first_seen_at"] = "2025-04-08T00:00:00+00:00"
    monthly = canonical({"date": "2025-04-07", "time": "8:30am", "currency": "USD",
                         "impact": "red", "event": "Shared Release", "event_id": "12345",
                         "url": "https://www.forexfactory.com/calendar/12345"},
                        "calendar_html", "2025-04")
    for record in (archive, monthly, archive, monthly):
        db.upsert([record])

    rows = db.rows()
    assert len(rows) == 1
    assert rows[0]["source_event_id"] == "12345"
    assert rows[0]["source_type"] == "calendar_html"
    assert rows[0]["first_seen_at"] == "2025-04-08T00:00:00+00:00"
    assert {source["source_type"] for source in db.sources(rows[0]["event_key"])} == {
        "huggingface_archive", "calendar_html"
    }
    archive_terminal = db.connection.execute(
        "SELECT MAX(e.date_et) FROM events e JOIN event_sources s ON s.event_key=e.event_key "
        "WHERE s.source_type='huggingface_archive'"
    ).fetchone()[0]
    assert archive_terminal == "2025-04-07"
    db.close()
