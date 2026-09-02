import csv
import hashlib
import io
from datetime import datetime
from pathlib import Path

import pytest

from ff_calendar_toolkit.configuration import find_configurations
from ff_calendar_toolkit.database import CalendarDatabase
from ff_calendar_toolkit.ingest import SourceError, _time, canonical, impact, parse_archive, parse_html
from ff_calendar_toolkit.pipeline import (CATEGORY_PREVALENCE_THRESHOLD,
                                          SPARSE_MONTH_MINIMUM_RATIO, validate)


def raw(day="2024-03-10", clock="1:30pm", event="Employment Change", impact_value="red", **kw):
    return {"date":day,"time":clock,"currency":"USD","event":event,"impact":impact_value,**kw}


def test_exact_impact_mapping():
    assert [impact(x) for x in ("red","orange","yellow","gray")]==[("red","High"),("orange","Medium"),("yellow","Low"),("gray","Non-Economic/Holiday")]
    with pytest.raises(SourceError): impact("purple")


@pytest.mark.parametrize("label", ["Day 1", "Day 2", "Day 4", "Day 10"])
def test_numbered_multi_day_labels_are_all_day(label):
    assert _time(label) == (None, True)


@pytest.mark.parametrize("label", ["All Day", "all day", "Tentative"])
def test_named_non_clock_labels_are_all_day(label):
    assert _time(label) == (None, True)


@pytest.mark.parametrize("month", [
    "Jan", "January", "Feb", "February", "Mar", "March", "Apr", "April", "May",
    "Jun", "June", "Jul", "July", "Aug", "August", "Sep", "Sept", "September",
    "Oct", "October", "Nov", "November", "Dec", "December",
])
def test_month_data_labels_are_non_clock_times_case_insensitively(month):
    assert _time(f"{month} Data") == (None, True)
    assert _time(f"{month.upper()} dAtA") == (None, True)


@pytest.mark.parametrize("label", [
    "Data Feb", "February Database", "Feb Data Extra", "Someday Data", "Month Data",
])
def test_month_data_lookalikes_are_rejected(label):
    with pytest.raises(SourceError, match="malformed time"):
        _time(label)


@pytest.mark.parametrize("label", [
    "Sep 27th", "September 27th", "Oct 4th", "Nov 1st", "FEB 29TH",
])
def test_month_ordinal_reference_dates_are_non_clock_times(label):
    assert _time(label) == (None, True)


@pytest.mark.parametrize("label", [
    "Sep 27", "27th Sep", "Sep 32nd", "Feb 30th", "Sep 27th Extra", "Sep 21th",
])
def test_invalid_or_inexact_month_ordinal_reference_dates_are_rejected(label):
    with pytest.raises(SourceError, match="malformed time"):
        _time(label)


@pytest.mark.parametrize("label", [
    "7th-14th", "7th - 14th", "7th–14th", "7th—14th", "1st-3rd", "21st-31st",
    "23rd-1st", "23rd - 1st", "28th–4th", "31st—3rd", "23rd-30th",
])
def test_ordinal_day_ranges_are_non_clock_times(label):
    assert _time(label) == (None, True)


@pytest.mark.parametrize("label", [
    "7-14", "7th to 14th", "14th-7th", "19th-1st", "23rd-8th",
    "0th-14th", "7th-32nd", "31st-32nd", "7st-14th", "7th-14st",
    "23th-1st", "23rd-1th", "7th-14th Extra", "23rd-1st Extra",
])
def test_invalid_or_inexact_ordinal_day_ranges_are_rejected(label):
    with pytest.raises(SourceError, match="malformed time"):
        _time(label)


@pytest.mark.parametrize("label", ["Daylight", "Someday 4", "Day Four", "Day 0", "Day -1"])
def test_unrelated_day_labels_are_rejected(label):
    with pytest.raises(SourceError, match="malformed time"):
        _time(label)


def test_day_four_canonical_event_has_no_clock_time_and_preserves_raw_value():
    event = canonical(raw(clock="Day 4"), "calendar_html", "2026-09")
    assert event["all_day"] is True
    assert event["time_et"] is event["datetime_et"] is event["datetime_utc"] is None
    assert event["raw_time"] == "Day 4"


def test_month_data_canonical_event_has_no_invented_clock_and_preserves_raw_value():
    event = canonical(raw(clock="fEbRuArY dAtA"), "calendar_html", "2025-10")
    assert event["all_day"] is True
    assert event["time_et"] is event["datetime_et"] is event["datetime_utc"] is None
    assert event["raw_time"] == "fEbRuArY dAtA"


def test_month_data_labels_distinguish_derived_event_keys_without_source_ids():
    february = canonical(raw(clock="Feb Data", event="PPI Input m/m"), "calendar_html", "2025-10")
    march = canonical(raw(clock="Mar Data", event="PPI Input m/m"), "calendar_html", "2025-10")

    assert february["source_event_id"] is march["source_event_id"] is None
    assert february["event_key"] != march["event_key"]


def test_reference_date_labels_are_clockless_and_distinguish_derived_keys():
    september = canonical(raw(clock="Sep 27th", event="Unemployment Claims"),
                          "calendar_html", "2025-11")
    october = canonical(raw(clock="Oct 4th", event="Unemployment Claims"),
                        "calendar_html", "2025-11")

    assert september["event_key"] != october["event_key"]
    assert september["raw_time"] == "Sep 27th"
    assert september["all_day"] is True
    assert september["time_et"] is september["datetime_et"] is september["datetime_utc"] is None


def test_ordinal_day_range_is_canonical_clockless_event_and_distinguishes_derived_keys():
    identified = canonical({
        "date": "2026-09-02", "time": "7th-14th", "currency": "EUR",
        "event": "German WPI m/m", "impact": "yellow", "source_event_id": "92002",
    }, "calendar_html", "2026-09")
    first_window = canonical(raw(clock="7th-14th", event="German WPI m/m"),
                             "calendar_html", "2026-09")
    second_window = canonical(raw(clock="15th-21st", event="German WPI m/m"),
                              "calendar_html", "2026-09")

    assert first_window["event_key"] != second_window["event_key"]
    assert identified["event_key"] == "ff:92002"
    assert identified["currency"] == "EUR"
    assert identified["event_name"] == "German WPI m/m"
    assert identified["raw_time"] == "7th-14th"
    assert identified["all_day"] is True
    assert identified["time_et"] is identified["datetime_et"] is identified["datetime_utc"] is None
    assert first_window["raw_time"] == "7th-14th"
    assert first_window["all_day"] is True
    assert first_window["time_et"] is first_window["datetime_et"] is first_window["datetime_utc"] is None


def test_cross_month_range_is_clockless_and_part_of_fallback_identity():
    first_window = canonical(raw(clock="23rd-1st", event="German Retail Sales m/m"),
                             "calendar_html", "2026-09")
    second_window = canonical(raw(clock="28th-4th", event="German Retail Sales m/m"),
                              "calendar_html", "2026-09")

    assert first_window["event_key"] != second_window["event_key"]
    assert first_window["raw_time"] == "23rd-1st"
    assert first_window["all_day"] is True
    assert first_window["time_et"] is first_window["datetime_et"] is first_window["datetime_utc"] is None


def test_production_ordinal_range_html_rows_do_not_inherit_neighboring_clock():
    html = '''<table><tr class="calendar__row calendar__row--day-breaker">
        <td class="calendar__date">Wed Sep 2 2026</td></tr>
        <tr class="calendar__row" data-event-id="92001">
        <td class="calendar__time">8:30am</td><td class="calendar__currency">USD</td>
        <td class="calendar__impact icon--ff-impact-red"></td>
        <td class="calendar__event">Neighboring Release</td></tr>
        <tr class="calendar__row" data-event-id="92002">
        <td class="calendar__time">23rd-30th</td><td class="calendar__currency">EUR</td>
        <td class="calendar__impact icon--ff-impact-yellow"></td>
        <td class="calendar__event">German Import Prices m/m</td></tr>
        <tr class="calendar__row" data-event-id="92003">
        <td class="calendar__time">23rd-1st</td><td class="calendar__currency">EUR</td>
        <td class="calendar__impact icon--ff-impact-yellow"></td>
        <td class="calendar__event">German Retail Sales m/m</td></tr></table>'''

    events = parse_html(html, "https://www.forexfactory.com/calendar", "2026-09")
    neighbor = next(event for event in events if event["source_event_id"] == "92001")
    ranges = [event for event in events if event["source_event_id"] in {"92002", "92003"}]

    assert neighbor["time_et"] == "08:30"
    assert neighbor["all_day"] is False
    assert [event["event_key"] for event in ranges] == ["ff:92002", "ff:92003"]
    assert [event["event_name"] for event in ranges] == [
        "German Import Prices m/m", "German Retail Sales m/m",
    ]
    assert [event["raw_time"] for event in ranges] == ["23rd-30th", "23rd-1st"]
    assert all(event["all_day"] is True for event in ranges)
    assert all(event["time_et"] is event["datetime_et"] is event["datetime_utc"] is None
               for event in ranges)


def test_production_reference_date_html_rows_with_source_ids_all_survive():
    rows = "".join(
        f'''<tr class="calendar__row" data-event-id="{event_id}">
        <td class="calendar__time">{clock}</td><td class="calendar__currency">USD</td>
        <td class="calendar__impact icon--ff-impact-red"></td>
        <td class="calendar__event">Unemployment Claims</td></tr>'''
        for event_id, clock in (
            ("81001", "Sep 27th"), ("81002", "Oct 4th"),
            ("81003", "Oct 11th"), ("81004", "2:10am"),
        )
    )
    html = ('''<table><tr class="calendar__row calendar__row--day-breaker">
            <td class="calendar__date">Tue Nov 18 2025</td></tr>'''
            + rows + "</table>")

    events = parse_html(html, "https://www.forexfactory.com/calendar", "2025-11")

    assert len(events) == 4
    assert {event["source_event_id"] for event in events} == {"81001", "81002", "81003", "81004"}
    assert all(event["time_et"] is None for event in events[:3])
    assert events[3]["time_et"] == "02:10"


@pytest.mark.parametrize("clock", ["All Day", "Tentative", "Day 1", "Day 4", ""])
def test_existing_non_clock_labels_preserve_legacy_derived_keys(clock):
    event = canonical(raw(clock=clock), "calendar_html", "2025-10")
    legacy_identity = "|".join(("2024-03-10", "ALL_DAY", "USD", "employment change"))

    assert event["event_key"] == "derived:" + hashlib.sha256(legacy_identity.encode()).hexdigest()


def test_repeated_archive_all_day_import_remains_idempotent(tmp_path):
    content = (b"date,time,currency,impact,event\n"
               b"2024-03-10,All Day,USD,red,Employment Change\n")
    database = CalendarDatabase(tmp_path / "calendar.sqlite")

    database.upsert(parse_archive(content))
    database.upsert(parse_archive(content))

    assert len(database.rows()) == 1
    legacy_identity = "|".join(("2024-03-10", "ALL_DAY", "USD", "employment change"))
    assert database.rows()[0]["event_key"] == (
        "derived:" + hashlib.sha256(legacy_identity.encode()).hexdigest()
    )
    database.close()


def test_day_four_html_event_is_canonical_all_day_event():
    html = '''<table><tr class="calendar__row"><td class="calendar__date">Wed Sep 2</td>
    <td class="calendar__time">Day 4</td><td class="calendar__currency">USD</td>
    <td class="calendar__impact icon--ff-impact-red"></td>
    <td class="calendar__event">Multi-day Meeting</td></tr></table>'''
    [event] = parse_html(html, "https://www.forexfactory.com/calendar", "2026-09")
    assert event["all_day"] is True
    assert event["time_et"] is None
    assert event["raw_time"] == "Day 4"


@pytest.mark.parametrize(
    ("css_class", "color", "level"),
    [
        (
            "calendar__cell calendar__impact icon icon--ff-impact-ora "
            "calendar__impact-icon calendar__impact-icon--print",
            "orange",
            "Medium",
        ),
        ("icon--ff-impact-red", "red", "High"),
        ("icon--ff-impact-yel", "yellow", "Low"),
        ("icon--ff-impact-gra", "gray", "Non-Economic/Holiday"),
    ],
)
def test_production_abbreviated_impact_class_tokens(css_class, color, level):
    assert impact(css_class) == (color, level)


@pytest.mark.parametrize("word", ["decorative", "style-yel-value", "paragraph"])
def test_impact_abbreviations_do_not_match_substrings(word):
    with pytest.raises(SourceError):
        impact(word)


@pytest.mark.parametrize(
    ("css_class", "expected"),
    [
        ("icon--ff-impact-orange", ("orange", "Medium")),
        ("icon--ff-impact-yellow", ("yellow", "Low")),
        ("icon--ff-impact-gray", ("gray", "Non-Economic/Holiday")),
    ],
)
def test_full_impact_class_tokens_remain_supported(css_class, expected):
    assert impact(css_class) == expected


def test_archive_import_idempotency_and_revision(tmp_path):
    content=b"date,time,currency,impact,event,actual,forecast,previous\n2024-01-01,8:30am,USD,red,Jobs,1,2,3\n"
    rows=parse_archive(content); db=CalendarDatabase(tmp_path/"db.sqlite")
    db.upsert(rows); first=db.rows()[0]["first_seen_at"]
    db.upsert(rows); assert len(db.rows())==1
    revised=canonical(raw(day="2024-01-01",clock="8:30am",event="Jobs",actual="9",source_event_id="42"),"test")
    db.upsert([revised]); revised["actual"]="10"; revised["time"]="9:00am"; db.upsert([revised])
    assert len(db.rows())==2 and next(r for r in db.rows() if r["source_event_id"]=="42")["actual"]=="10"


PRODUCTION_ARCHIVE_CSV = b"""DateTime,Currency,Impact,Event,Actual,Forecast,Previous,Detail
2007-01-03T16:45:00+03:30,USD,High Impact Expected,ADP Non-Farm Employment Change,,,,
"""


def assert_production_archive_rows(rows):
    [adp] = rows
    assert adp["event_name"] == "ADP Non-Farm Employment Change"
    assert (adp["impact_color"], adp["impact_level"]) == ("red", "High")
    assert impact("Medium Impact Expected") == ("orange", "Medium")
    # 16:45 at UTC+03:30 is 13:15 UTC and 08:15 in New York in January.
    assert (adp["date_et"], adp["time_et"]) == ("2007-01-03", "08:15")
    assert datetime.fromisoformat(adp["datetime_et"]).utcoffset().total_seconds() == -5 * 60 * 60


def test_production_archive_datetime_header_and_timezone_conversion():
    assert_production_archive_rows(parse_archive(PRODUCTION_ARCHIVE_CSV))


def test_archive_date_and_date_et_headers_remain_supported():
    for header in ("date", "date_et"):
        content = f"{header},time,currency,impact,event\n2024-01-10,8:30am,USD,red,Jobs\n".encode()
        row = parse_archive(content)[0]
        assert (row["date_et"], row["time_et"]) == ("2024-01-10", "08:30")


def test_production_parquet_archive_datetime_header_and_timezone_conversion():
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    frame = pd.read_csv(io.BytesIO(PRODUCTION_ARCHIVE_CSV), keep_default_na=False)
    parquet = io.BytesIO()
    frame.to_parquet(parquet, index=False)
    assert_production_archive_rows(parse_archive(parquet.getvalue(), "archive.parquet"))


HTML='''<table><tr class="calendar__row"><td class="calendar__date">WedAug 2</td><td class="calendar__time">8:15am</td><td class="calendar__currency">USD</td><td class="calendar__impact"><span class="icon--ff-impact-red"></span></td><td class="calendar__event"><a href="/calendar/1">ADP Non-Farm Employment Change</a></td></tr><tr class="calendar__row"><td class="calendar__time"></td><td class="calendar__currency">EUR</td><td class="calendar__impact icon--ff-impact-orange"></td><td class="calendar__event">Simultaneous Event</td></tr><tr class="calendar__row"><td class="calendar__date">ThuAug 3</td><td class="calendar__time">All Day</td><td class="calendar__currency">ALL</td><td class="calendar__impact icon--ff-impact-gray"></td><td class="calendar__event">Holiday</td></tr></table>'''


def test_html_time_propagation_simultaneous_and_all_day():
    rows=parse_html(HTML,"https://www.forexfactory.com/calendar","2023-08")
    assert rows[0]["time_et"]==rows[1]["time_et"]=="08:15"
    assert rows[2]["all_day"] and rows[2]["time_et"] is None


def test_html_month_data_does_not_inherit_preceding_event_clock():
    html = '''<table>
    <tr class="calendar__row"><td class="calendar__date">Wed Oct 22</td>
      <td class="calendar__time">4:30am</td><td class="calendar__currency">GBP</td>
      <td class="calendar__impact icon--ff-impact-red"></td>
      <td class="calendar__event">Timed Release</td></tr>
    <tr class="calendar__row"><td class="calendar__time">Feb Data</td>
      <td class="calendar__currency">GBP</td><td class="calendar__impact icon--ff-impact-yellow"></td>
      <td class="calendar__event">PPI Input m/m</td></tr>
    <tr class="calendar__row"><td class="calendar__currency">GBP</td>
      <td class="calendar__impact icon--ff-impact-yellow"></td>
      <td class="calendar__event">PPI Output m/m</td></tr></table>'''
    rows = parse_html(html, "https://www.forexfactory.com/calendar", "2025-10")
    assert rows[0]["time_et"] == "04:30"
    for event in rows[1:]:
        assert event["all_day"] is True
        assert event["time_et"] is event["datetime_et"] is event["datetime_utc"] is None
        assert event["raw_time"] == "Feb Data"


def test_verification_and_empty_pages_rejected():
    for page in ("<title>Verify you are human</title>","<html>nothing</html>"):
        with pytest.raises(SourceError): parse_html(page)


def test_month_year_boundaries_and_dst_conversion():
    dec=canonical(raw(day="2023-12-31",clock="11:30pm"),"test")
    jan=canonical(raw(day="2024-01-01",clock="12:30am"),"test")
    winter=canonical(raw(day="2024-01-10",clock="8:30am"),"test")
    summer=canonical(raw(day="2024-07-10",clock="8:30am"),"test")
    assert dec["date_et"] < jan["date_et"]
    assert datetime.fromisoformat(winter["datetime_utc"]).hour==13
    assert datetime.fromisoformat(summer["datetime_utc"]).hour==12


def test_configuration_matching_not_hardcoded():
    rows=[]
    for day, extras in (("2023-08-02",[]),("2023-12-06",[]),("2024-05-01",["ISM Manufacturing PMI"])):
        rows.append(canonical(raw(day=day,event="ADP Non-Farm Employment Change",impact_value="orange"),"test"))
        rows += [canonical(raw(day=day,event=e,impact_value="red"),"test") for e in extras]
        rows.append(canonical(raw(day=day,event="Minor",impact_value="yellow"),"test"))
    result=find_configurations(rows,"ADP Non-Farm Employment Change",["USD","EUR"],["red","orange"],True)
    assert [x["matched"] for x in result]==[True,True,False]


def test_deterministic_csv_and_duplicate_validation(tmp_path):
    db=CalendarDatabase(tmp_path/"db.sqlite"); db.upsert([canonical(raw(),"test")])
    db.export(["csv"],tmp_path/"a"); db.export(["csv"],tmp_path/"b")
    assert (tmp_path/"a/forex_factory_calendar_full.csv").read_bytes()==(tmp_path/"b/forex_factory_calendar_full.csv").read_bytes()
    manifest,errors=validate(db); assert manifest["duplicate_count"]==0


def _coverage_records(month, source_type, count=8):
    currencies = ("USD", "EUR", "GBP", "JPY")
    impacts = ("red", "orange", "yellow", "gray")
    return [canonical({"date": f"{month}-{index + 1:02d}", "time": "8:30am",
        "currency": currencies[index % len(currencies)], "impact": impacts[index % len(impacts)],
        "event": f"Event {month} {index}"}, source_type, month) for index in range(count)]


def test_manifest_audits_month_counts_sources_and_filtered_browser_month(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    for month in ("2024-01", "2024-02", "2024-03"):
        records = _coverage_records(month, "huggingface_archive")
        db.upsert(records); db.mark_period(month, "complete", len(records), source_type="huggingface_archive")
    sparse = _coverage_records("2025-01", "calendar_html", 1)
    db.upsert(sparse); db.mark_period("2025-01", "complete", 1, source_type="calendar_html")

    manifest, errors = validate(db, strict=True, write_manifest=False)

    assert SPARSE_MONTH_MINIMUM_RATIO == 0.25
    assert CATEGORY_PREVALENCE_THRESHOLD == 0.80
    assert manifest["event_count_by_month"]["2025-01"] == 1
    assert manifest["count_by_month_and_impact_color"]["2025-01"] == {"red": 1}
    assert manifest["count_by_month_and_currency"]["2025-01"] == {"USD": 1}
    assert manifest["source_count_by_month"]["2025-01"] == {"calendar_html": 1}
    assert manifest["suspiciously_sparse_completed_months"] == ["2025-01"]
    assert manifest["completeness_baseline"]["median_events_per_complete_archive_month"] == 8
    assert any("suspiciously sparse or filtered" in error for error in errors)


def test_expected_category_audit_rejects_red_orange_only_and_narrow_currency(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    for month in ("2024-01", "2024-02", "2024-03"):
        archive = _coverage_records(month, "huggingface_archive")
        db.upsert(archive); db.mark_period(month, "complete", len(archive), source_type="huggingface_archive")
    filtered = _coverage_records("2025-01", "calendar_html")
    for record in filtered:
        record["impact_color"] = "red" if record["impact_color"] in {"red", "yellow"} else "orange"
        record["impact_level"] = "High" if record["impact_color"] == "red" else "Medium"
        record["currency"] = "USD"
    db.upsert(filtered); db.mark_period("2025-01", "complete", len(filtered), source_type="calendar_html")
    manifest, _errors = validate(db, strict=True, write_manifest=False)
    reasons = manifest["browser_month_issues"]["2025-01"]
    assert "missing normally expected impact colors: gray, yellow" in reasons
    assert "missing normally expected major currencies: EUR, GBP, JPY" in reasons


def test_complete_category_page_passes_and_current_future_are_exempt(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    for month in ("2024-01", "2024-02", "2024-03"):
        archive = _coverage_records(month, "huggingface_archive")
        db.upsert(archive); db.mark_period(month, "complete", len(archive), source_type="huggingface_archive")
    complete = _coverage_records("2025-01", "calendar_html")
    db.upsert(complete); db.mark_period("2025-01", "complete", len(complete), source_type="calendar_html")
    current = datetime.now().strftime("%Y-%m")
    partial = [canonical({"date": f"{current}-01", "time": "8:30am", "currency": "USD",
        "impact": "red", "event": "Partial current event"}, "calendar_html", current)]
    db.upsert(partial); db.mark_period(current, "complete", 1, source_type="calendar_html")
    manifest, _errors = validate(db, strict=True, write_manifest=False)
    assert "2025-01" not in manifest["browser_month_issues"]
    assert current not in manifest["browser_month_issues"]


def test_incomplete_period_is_retained_for_retry(tmp_path):
    db=CalendarDatabase(tmp_path/"db.sqlite"); db.mark_period("2025-05","incomplete",error="blocked")
    assert db.connection.execute("SELECT status FROM periods WHERE period='2025-05'").fetchone()[0]=="incomplete"
