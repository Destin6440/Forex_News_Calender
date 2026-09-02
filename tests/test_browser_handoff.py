from datetime import date
from pathlib import Path

import pytest

from ff_calendar_toolkit.browser_handoff import ChromeHandoff
from ff_calendar_toolkit.cli import build_parser
from ff_calendar_toolkit.ingest import SourceError
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
    clock = iter((0.0, 0.1))
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
