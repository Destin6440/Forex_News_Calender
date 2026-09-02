from datetime import date

import pytest

from ff_calendar_toolkit.cli import build_parser
from ff_calendar_toolkit.database import CalendarDatabase
from ff_calendar_toolkit.pipeline import (
    ChromeHandoffBrowser,
    bootstrap,
    repair_existing_partial_archive_period,
)


def calendar_html(day="Wed Apr 9", event="Employment Report"):
    return f"""
    <table><tr class="calendar__row calendar_row">
      <td class="calendar__date date"><span>{day}</span></td>
      <td class="calendar__time time"><span>8:30am</span></td>
      <td class="calendar__currency currency"><span>USD</span></td>
      <td class="calendar__impact impact icon--ff-impact-red"></td>
      <td class="calendar__event event"><span>{event}</span></td>
    </tr></table>
    """


class FakeProcess:
    def __init__(self):
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True


class FakeOptions:
    def __init__(self):
        self.experimental = {}

    def add_experimental_option(self, name, value):
        self.experimental[name] = value


class FakeDriver:
    def __init__(self, page):
        self.page = page
        self.urls = []
        self.quit_count = 0

    @property
    def page_source(self):
        return self.page

    def get(self, url):
        self.urls.append(url)
        self.page = calendar_html("Thu May 8", "Second Event")

    def quit(self):
        self.quit_count += 1


def test_cli_exposes_mutually_exclusive_browser_handoff():
    parser = build_parser()
    assert parser.parse_args(["sync", "--browser-handoff"]).browser_handoff
    assert parser.parse_args([
        "backfill", "--start", "2025-04-01", "--end", "today", "--browser-handoff"
    ]).browser_handoff
    with pytest.raises(SystemExit):
        parser.parse_args(["sync", "--browser-handoff", "--interactive-browser"])


def test_handoff_starts_ordinary_chrome_and_attaches_only_after_confirmation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    actions = []
    commands = []
    process = FakeProcess()
    driver = FakeDriver(calendar_html())
    captured_options = []

    def process_factory(command):
        actions.append("process")
        commands.append(command)
        return process

    def debugger_wait(port, launched_process):
        actions.append("debugger-ready")
        assert port == 9234
        assert launched_process is process

    def input_fn(_prompt):
        actions.append("human-confirmed")
        return ""

    def driver_factory(options):
        actions.append("webdriver-attached")
        captured_options.append(options)
        return driver

    browser = ChromeHandoffBrowser(
        input_fn=input_fn,
        output=lambda _message: None,
        process_factory=process_factory,
        driver_factory=driver_factory,
        options_factory=FakeOptions,
        debugger_wait=debugger_wait,
        port_factory=lambda: 9234,
        chrome_binary="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )
    try:
        _text, rows = browser.retrieve(date(2025, 4, 1))
    finally:
        browser.close()

    assert actions == ["process", "debugger-ready", "human-confirmed", "webdriver-attached"]
    command = commands[0]
    assert command[0].endswith("/Google Chrome")
    assert "--remote-debugging-address=127.0.0.1" in command
    assert "--remote-debugging-port=9234" in command
    assert any("data/chrome-handoff-profile" in item for item in command)
    assert not any("headless" in item or "enable-automation" in item for item in command)
    assert captured_options[0].experimental == {"debuggerAddress": "127.0.0.1:9234"}
    assert rows[0]["event_name"] == "Employment Report"
    assert driver.quit_count == 1


def test_handoff_reuses_attached_browser_for_later_months(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    driver = FakeDriver(calendar_html())
    starts = []
    sleeps = []
    browser = ChromeHandoffBrowser(
        input_fn=lambda _prompt: "",
        output=lambda _message: None,
        sleep=sleeps.append,
        process_factory=lambda command: starts.append(command) or FakeProcess(),
        driver_factory=lambda _options: driver,
        options_factory=FakeOptions,
        debugger_wait=lambda _port, _process: None,
        port_factory=lambda: 9234,
        chrome_binary="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )
    try:
        browser.retrieve(date(2025, 4, 1))
        _text, rows = browser.retrieve(date(2025, 5, 1))
    finally:
        browser.close()

    assert len(starts) == 1
    assert len(driver.urls) == 1
    assert driver.urls[0].endswith("month=may.2025")
    assert sleeps == [5.0, 3.0]
    assert rows[0]["event_name"] == "Second Event"


def test_real_challenge_returns_control_to_human(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    challenge = "<html><title>Just a moment...</title><div id='cf-chl-widget'></div></html>"
    driver = FakeDriver(challenge)
    prompts = []

    def input_fn(prompt):
        prompts.append(prompt)
        if len(prompts) == 2:
            driver.page = calendar_html()
        return ""

    browser = ChromeHandoffBrowser(
        input_fn=input_fn,
        output=lambda _message: None,
        process_factory=lambda _command: FakeProcess(),
        driver_factory=lambda _options: driver,
        options_factory=FakeOptions,
        debugger_wait=lambda _port, _process: None,
        port_factory=lambda: 9234,
        chrome_binary="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )
    try:
        _text, rows = browser.retrieve(date(2025, 4, 1))
    finally:
        browser.close()

    assert len(prompts) == 2
    assert rows[0]["event_name"] == "Employment Report"


def test_existing_database_repairs_partial_archive_tail_once(tmp_path):
    db = CalendarDatabase(tmp_path / "calendar.sqlite")
    try:
        db.mark_period("2025-04", "complete", 10, source_type="huggingface_archive")
        assert repair_existing_partial_archive_period(db) is True
        repaired = db.connection.execute(
            "SELECT * FROM periods WHERE period='2025-04'"
        ).fetchone()
        assert repaired["status"] == "incomplete"
        assert "2025-04-07" in repaired["error"]

        db.mark_period("2025-04", "complete", 100, source_type="calendar_html")
        assert repair_existing_partial_archive_period(db) is False
        assert db.connection.execute(
            "SELECT status FROM periods WHERE period='2025-04'"
        ).fetchone()[0] == "complete"
    finally:
        db.close()


def test_bootstrap_marks_partial_terminal_archive_month_incomplete(tmp_path):
    archive = tmp_path / "archive.csv"
    archive.write_text(
        "date,time,currency,impact,event\n"
        "2025-03-31,8:30am,USD,red,March Event\n"
        "2025-04-07,8:30am,USD,red,April Event\n",
        encoding="utf-8",
    )
    db = CalendarDatabase(tmp_path / "calendar.sqlite")
    try:
        assert bootstrap(db, str(archive)) == 2
        periods = {
            row["period"]: dict(row)
            for row in db.connection.execute("SELECT * FROM periods ORDER BY period")
        }
        assert periods["2025-03"]["status"] == "complete"
        assert periods["2025-04"]["status"] == "incomplete"
        assert "2025-04-07" in periods["2025-04"]["error"]
    finally:
        db.close()
