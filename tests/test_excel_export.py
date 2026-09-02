from datetime import date, time

import pytest

openpyxl = pytest.importorskip("openpyxl")

from ff_calendar_toolkit.database import CalendarDatabase
from ff_calendar_toolkit.excel_export import EVENT_HEADERS, SOURCE_HEADERS, export_yearly_excel
from ff_calendar_toolkit.ingest import canonical


def _record(day, clock, name, impact="red"):
    return canonical({"date": day, "time": clock, "currency": "USD", "impact": impact,
                      "event": name}, "calendar_html", day[:7])


def test_year_partition_structure_types_order_and_idempotency(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    records = [_record("2025-01-02", "Day 4", "All Day"),
               _record("2025-01-01", "8:30am", "Clock", "orange"),
               _record("2026-02-01", "9:00am", "Next Year", "yellow")]
    db.upsert(records)
    output = tmp_path / "News Data"; unrelated = output / "keep.txt"
    output.mkdir(); unrelated.write_text("keep")
    manifest = {"generated_at": "2026-09-02T00:00:00+00:00", "last_successful_synchronization": None}
    paths = export_yearly_excel(db, output, manifest)
    assert [path.name for path in paths] == ["Forex_Factory_News_2025.xlsx", "Forex_Factory_News_2026.xlsx"]
    workbook = openpyxl.load_workbook(paths[0])
    assert workbook.sheetnames == ["Events", "Sources", "Summary"]
    events = workbook["Events"]; sources = workbook["Sources"]
    assert [cell.value for cell in events[1]] == EVENT_HEADERS
    assert [cell.value for cell in sources[1]] == SOURCE_HEADERS
    assert isinstance(events[2][1].value, date) and isinstance(events[2][2].value, time)
    assert events[3][2].value is None and events[3][3].value is True
    assert events.freeze_panes == "A2" and events.auto_filter.ref
    assert events.tables and sources.tables
    assert events[2][5].fill.fgColor.rgb.endswith("FCE5CD")
    assert events.max_row - 1 == 2 and sources.max_row - 1 == 2
    workbook.close()
    export_yearly_excel(db, output, manifest)
    assert unrelated.read_text() == "keep"
    assert openpyxl.load_workbook(paths[0])["Events"].max_row - 1 == 2


def test_failed_generation_preserves_previous_workbooks(monkeypatch, tmp_path):
    import ff_calendar_toolkit.excel_export as module
    db = CalendarDatabase(tmp_path / "db.sqlite"); db.upsert([_record("2025-01-01", "8:30am", "Event")])
    output = tmp_path / "News Data"; output.mkdir()
    old = output / "Forex_Factory_News_2025.xlsx"; old.write_bytes(b"previous")
    monkeypatch.setattr(module, "_verify", lambda *_args: (_ for _ in ()).throw(RuntimeError("verify failed")))
    with pytest.raises(RuntimeError, match="verify failed"):
        export_yearly_excel(db, output, {"generated_at": "now"})
    assert old.read_bytes() == b"previous"
