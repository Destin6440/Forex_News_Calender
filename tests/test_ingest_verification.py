import pytest

from ff_calendar_toolkit.ingest import SourceError, VerificationPageError, parse_html


def calendar_row(
    *,
    date: str | None = None,
    time: str | None = None,
    currency: str | None = None,
    event: str | None = None,
    impact: str | None = "icon--ff-impact-red",
) -> str:
    cells = []
    if date is not None:
        cells.append(f'<td class="calendar__date date">{date}</td>')
    if time is not None:
        cells.append(f'<td class="calendar__time time">{time}</td>')
    if currency is not None:
        cells.append(f'<td class="calendar__currency currency">{currency}</td>')
    if impact is not None:
        cells.append(f'<td class="calendar__impact impact {impact}"></td>')
    if event is not None:
        cells.append(f'<td class="calendar__event event">{event}</td>')
    return '<tr class="calendar__row calendar_row">' + "".join(cells) + "</tr>"


def calendar_page(*rows: str, extra_html: str = "") -> str:
    return f"""
    <html>
      <head>{extra_html}</head>
      <body><table class="calendar__table">{"".join(rows)}</table></body>
    </html>
    """


def valid_row(**overrides: str | None) -> str:
    values = {
        "date": "Wed May 7",
        "time": "8:30am",
        "currency": "USD",
        "event": "Employment Report",
    }
    values.update(overrides)
    return calendar_row(**values)


def test_valid_calendar_rows_win_over_unrelated_cloudflare_text():
    html = calendar_page(
        valid_row(),
        extra_html='<meta name="cdn" content="cloudflare"><script src="/cloudflare/analytics.js"></script>',
    )

    events = parse_html(html, period="2025-05")

    assert [event["event_name"] for event in events] == ["Employment Report"]


def test_genuine_challenge_page_raises_verification_error():
    challenge = "<html><title>Just a moment...</title><div id='cf-chl-widget'>Security check</div></html>"

    with pytest.raises(VerificationPageError):
        parse_html(challenge)


def test_ordinary_empty_page_raises_source_error():
    with pytest.raises(SourceError, match="no recognizable calendar rows") as error:
        parse_html("<html><body>No events are available.</body></html>")

    assert not isinstance(error.value, VerificationPageError)


def test_date_only_empty_day_is_not_an_event_and_does_not_fail_page():
    html = calendar_page(
        valid_row(date="Sat May 10", event="Consumer Sentiment"),
        calendar_row(date="Sun May 11", impact=None),
    )

    events = parse_html(html, period="2025-05")

    assert len(events) == 1
    assert events[0]["event_name"] == "Consumer Sentiment"
    assert all(event["event_name"] != "No news" for event in events)


def test_date_only_row_updates_context_for_following_event():
    html = calendar_page(
        valid_row(date="Sat May 10", event="Consumer Sentiment"),
        calendar_row(date="Sun May 11", impact=None),
        calendar_row(time="9:00am", currency="EUR", event="Eurogroup Meetings"),
    )

    events = parse_html(html, period="2025-05")

    assert [event["date_et"] for event in events] == ["2025-05-10", "2025-05-11"]
    assert events[1]["event_name"] == "Eurogroup Meetings"


@pytest.mark.parametrize(
    "row",
    [
        calendar_row(date="Wed May 7", time="8:30am", event="Employment Report"),
        calendar_row(date="Wed May 7", time="8:30am", currency="USD"),
    ],
    ids=["missing-currency", "missing-event-name"],
)
def test_partially_populated_event_row_fails_page(row):
    with pytest.raises(SourceError, match="missing an event name or currency"):
        parse_html(calendar_page(row), period="2025-05")


def test_event_row_without_date_context_fails_page():
    row = calendar_row(time="8:30am", currency="USD", event="Employment Report")

    with pytest.raises(SourceError, match="no date and no preceding date"):
        parse_html(calendar_page(row), period="2025-05")


def test_malformed_event_row_mixed_with_valid_rows_fails_entire_page():
    malformed = calendar_row(time="10:00am", event="Missing Currency Event")

    with pytest.raises(SourceError, match="missing an event name or currency"):
        parse_html(calendar_page(valid_row(), malformed), period="2025-05")


def test_simultaneous_event_inherits_previous_time():
    html = calendar_page(
        valid_row(time="8:30am", event="Non-Farm Employment Change"),
        calendar_row(currency="CAD", event="Employment Change", impact="icon--ff-impact-orange"),
    )

    events = parse_html(html, period="2025-05")

    assert [event["time_et"] for event in events] == ["08:30", "08:30"]
