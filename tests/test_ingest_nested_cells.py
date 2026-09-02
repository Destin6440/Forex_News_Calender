from pathlib import Path

import pytest

from ff_calendar_toolkit.ingest import SourceError, parse_html


FIXTURE = Path(__file__).parent / "fixtures" / "forex_factory_nested_calendar.html"


def test_nested_production_cells_are_parsed_without_losing_parent_context():
    events = parse_html(
        FIXTURE.read_text(encoding="utf-8"),
        source_url="https://www.forexfactory.com/calendar?month=may.2025",
        period="2025-05",
    )

    assert [event["currency"] for event in events] == ["USD", "CAD", "EUR"]
    assert [event["event_name"] for event in events] == [
        "Employment Report",
        "Employment Change",
        "Central Bank Bulletin",
    ]
    assert events[0]["actual"] == "177K"
    assert events[0]["forecast"] == "138K"
    assert events[0]["previous"] == "185K"
    assert events[0]["impact_color"] == "red"
    assert events[1]["impact_color"] == "orange"
    assert events[0]["source_url"] == "https://www.forexfactory.com/calendar/123-employment-report"


def test_simultaneous_release_inherits_time_and_date_only_row_creates_no_event():
    events = parse_html(FIXTURE.read_text(encoding="utf-8"), period="2025-05")

    assert len(events) == 3
    assert [event["time_et"] for event in events[:2]] == ["08:30", "08:30"]
    assert [event["date_et"] for event in events] == ["2025-05-07", "2025-05-07", "2025-05-08"]


@pytest.mark.parametrize(
    ("partial_cell", "missing"),
    [
        ('<td class="calendar__event event"><span>Employment Report</span></td>', "currency"),
        ('<td class="calendar__currency currency"><span>USD</span></td>', "event name"),
    ],
)
def test_nested_partial_rows_report_row_cells_and_missing_field(partial_cell, missing):
    html = f"""
    <table>
      <tr class="calendar__row"><td class="calendar__date date">Wed May 7</td></tr>
      <tr class="calendar__row">{partial_cell}</tr>
    </table>
    """

    with pytest.raises(SourceError) as error:
        parse_html(html, period="2025-05")

    message = str(error.value)
    assert "calendar row 2" in message
    assert f"missing {missing}" in message
    assert "recognized cells" in message
    assert "<table>" not in message
