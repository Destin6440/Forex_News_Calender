from datetime import date

import pytest

from ff_calendar_toolkit.cli import build_parser
from ff_calendar_toolkit.database import CalendarDatabase
from ff_calendar_toolkit.ingest import SourceError, VerificationPageError
from ff_calendar_toolkit.pipeline import CalendarBrowser, backfill


CALENDAR_HTML = """
<table><tr class="calendar__row">
<td class="calendar__date">Wed May 7</td>
<td class="calendar__time">8:30am</td>
<td class="calendar__currency">USD</td>
<td class="calendar__impact icon--ff-impact-red"></td>
<td class="calendar__event">Employment Report</td>
</tr></table>
"""


class FakeDriver:
    def __init__(self, pages):
        self.pages = list(pages)
        self.page_index = 0
        self.urls = []
        self.quit_count = 0

    def get(self, url):
        self.urls.append(url)

    @property
    def page_source(self):
        return self.pages[min(self.page_index, len(self.pages) - 1)]

    def quit(self):
        self.quit_count += 1


class FakeOptions:
    def __init__(self):
        self.arguments = []

    def add_argument(self, argument):
        self.arguments.append(argument)


def test_cli_exposes_interactive_browser_for_backfill_and_sync():
    parser = build_parser()
    backfill_args = parser.parse_args(
        ["backfill", "--start", "2025-05-01", "--end", "2025-05-31", "--interactive-browser"]
    )
    sync_args = parser.parse_args(["sync", "--interactive-browser"])
    assert backfill_args.interactive_browser is True
    assert sync_args.interactive_browser is True


def test_interactive_browser_waits_for_manual_verification_and_persists_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    driver = FakeDriver(["<title>Verify you are human</title>", CALENDAR_HTML])
    messages = []
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            driver.page_index = 1

    captured_options = []
    browser = CalendarBrowser(
        interactive=True,
        driver_factory=lambda options: captured_options.append(options) or driver,
        options_factory=FakeOptions,
        sleep=sleep,
        monotonic=lambda: 0,
        output=messages.append,
    )
    _html, rows = browser.retrieve(date(2025, 5, 1))
    browser.close()

    arguments = captured_options[0].arguments
    assert "--headless=new" not in arguments
    assert any(arg.startswith("--user-data-dir=") and "data/chrome-profile" in arg for arg in arguments)
    assert (tmp_path / "data" / "chrome-profile").is_dir()
    assert len(rows) == 1
    assert any("manually" in message and "10 minutes" in message for message in messages)
    assert driver.quit_count == 1


def test_interactive_browser_rejects_non_verification_html_immediately(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    driver = FakeDriver(["<html><body>malformed ordinary response</body></html>"])
    messages = []
    sleeps = []
    browser = CalendarBrowser(
        interactive=True,
        driver_factory=lambda _options: driver,
        options_factory=FakeOptions,
        sleep=sleeps.append,
        monotonic=lambda: pytest.fail("recovery deadline must not start"),
        output=messages.append,
    )

    with pytest.raises(SourceError, match="no recognizable calendar rows"):
        browser.retrieve(date(2025, 5, 1))

    # The sole sleep is the normal initial page-load delay, not recovery polling.
    assert sleeps == [3.0]
    assert messages == []
    browser.close()


def test_interactive_browser_verification_timeout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    driver = FakeDriver(["<title>Verify you are human</title>"])
    messages = []
    monotonic_values = iter((0, 600))
    browser = CalendarBrowser(
        interactive=True,
        driver_factory=lambda _options: driver,
        options_factory=FakeOptions,
        sleep=lambda _seconds: None,
        monotonic=lambda: next(monotonic_values),
        output=messages.append,
    )

    with pytest.raises(VerificationPageError):
        browser.retrieve(date(2025, 5, 1))

    assert len(messages) == 1
    assert "VERIFICATION REQUIRED" in messages[0]
    browser.close()


def test_backfill_reuses_one_mocked_driver_and_reports_each_month(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    driver = FakeDriver([CALENDAR_HTML])
    starts = []
    browser = CalendarBrowser(
        driver_factory=lambda options: starts.append(options) or driver,
        options_factory=FakeOptions,
        sleep=lambda _seconds: None,
    )
    db = CalendarDatabase(tmp_path / "calendar.sqlite")
    try:
        count = backfill(db, date(2025, 5, 1), date(2025, 6, 30), browser=browser)
        statuses = list(db.connection.execute("SELECT period,status FROM periods ORDER BY period"))
    finally:
        db.close()
        browser.close()

    output = capsys.readouterr().out
    assert count == 2
    assert len(starts) == 1
    assert len(driver.urls) == 2
    assert [(row[0], row[1]) for row in statuses] == [
        ("2025-05", "complete"), ("2025-06", "complete")
    ]
    for period in ("2025-05", "2025-06"):
        assert f"Retrieving month {period}" in output
        assert f"Month {period} complete: 1 rows" in output
