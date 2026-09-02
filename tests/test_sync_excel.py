from datetime import date
from pathlib import Path

import pytest

from ff_calendar_toolkit.cli import build_parser, run_data_command
from ff_calendar_toolkit.database import CalendarDatabase
from ff_calendar_toolkit.ingest import SourceError, canonical
from ff_calendar_toolkit.pipeline import sync, sync_months


def test_sync_cli_options_and_standalone_excel_command():
    parser = build_parser()
    args = parser.parse_args(["sync", "--browser-handoff", "--force-refresh-start", "2025-04-01",
                              "--yearly-excel-dir", "/tmp/News Data"])
    assert args.force_refresh_start == date(2025, 4, 1)
    assert args.yearly_excel_dir == Path("/tmp/News Data")
    exported = parser.parse_args(["export-yearly-excel", "--output-dir", "/tmp/News Data"])
    assert exported.output_dir == Path("/tmp/News Data")


def test_standalone_excel_command_validates_then_exports(monkeypatch, tmp_path, capsys):
    import ff_calendar_toolkit.database as database
    import ff_calendar_toolkit.excel_export as excel
    import ff_calendar_toolkit.pipeline as pipeline
    db = CalendarDatabase(tmp_path / "db.sqlite")
    exported = []
    monkeypatch.setattr(database, "CalendarDatabase", lambda: db)
    monkeypatch.setattr(pipeline, "validate", lambda *_args, **_kwargs: ({"generated_at": "now"}, []))
    monkeypatch.setattr(excel, "export_yearly_excel", lambda _db, directory, _manifest: exported.append(directory) or [])
    args = build_parser().parse_args(["export-yearly-excel", "--output-dir", str(tmp_path / "News Data")])
    assert run_data_command(args) == 0
    assert exported == [tmp_path / "News Data"]
    assert capsys.readouterr().out.strip() == "[]"


def _event(day, source="huggingface_archive"):
    return canonical({"date": day, "time": "8:30am", "currency": "USD", "impact": "red",
                      "event": f"Event {day}"}, source, day[:7])


def test_sync_month_plan_deduplicates_force_gaps_and_revision_window(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    db.upsert([_event("2025-04-07")])
    for month in ("2025-04", "2025-05", "2025-07", "2025-08"):
        db.mark_period(month, "complete", 1, source_type="calendar_html")
    months = sync_months(db, date(2025, 4, 1), today=date(2025, 8, 15))
    labels = [month.strftime("%Y-%m") for month in months]
    assert labels == ["2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09"]
    assert len(labels) == len(set(labels))


def test_normal_incremental_plan_without_force_keeps_gap_and_revision_policy(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    db.upsert([_event("2025-04-07")])
    for month in ("2025-04", "2025-05", "2025-07"):
        db.mark_period(month, "complete", 1, source_type="calendar_html")
    labels = [month.strftime("%Y-%m") for month in sync_months(db, today=date(2025, 8, 15))]
    assert labels == ["2025-06", "2025-07", "2025-08", "2025-09"]


def test_sync_uses_one_browser_and_excel_failure_prevents_state(monkeypatch, tmp_path):
    import ff_calendar_toolkit.browser_handoff as handoff
    import ff_calendar_toolkit.excel_export as excel
    import ff_calendar_toolkit.pipeline as pipeline
    db = CalendarDatabase(tmp_path / "db.sqlite")
    browser = object(); entered = []; retrieved = []
    class Context:
        def __enter__(self): entered.append(True); return browser
        def __exit__(self, *_args): pass
    monkeypatch.setattr(pipeline, "DATA", tmp_path / "data")
    monkeypatch.setattr(pipeline, "bootstrap", lambda *_args: 0)
    monkeypatch.setattr(handoff, "ChromeHandoff", lambda *_args: Context())
    monkeypatch.setattr(pipeline, "sync_months", lambda *_args: [date(2025, 4, 1), date(2025, 5, 1)])
    monkeypatch.setattr(pipeline, "backfill", lambda _db, month, _end, browser=None: retrieved.append((month, browser)) or 1)
    monkeypatch.setattr(pipeline, "update", lambda _db: 0)
    monkeypatch.setattr(pipeline, "validate", lambda *_args, **_kwargs: ({"latest_event_date": "2025-05-01"}, []))
    monkeypatch.setattr(db, "export", lambda *_args: {})
    monkeypatch.setattr(excel, "export_yearly_excel", lambda *_args: (_ for _ in ()).throw(RuntimeError("excel failed")))
    with pytest.raises(RuntimeError, match="excel failed"):
        sync(db, browser_handoff=True, yearly_excel_dir=tmp_path / "excel")
    assert len(entered) == 1
    assert [item[0] for item in retrieved] == [date(2025, 4, 1), date(2025, 5, 1)]
    assert all(item[1] is browser for item in retrieved)
    assert not (tmp_path / "data" / "sync_state.json").exists()


def test_sync_validation_failure_does_not_invoke_excel(monkeypatch, tmp_path):
    import ff_calendar_toolkit.excel_export as excel
    import ff_calendar_toolkit.pipeline as pipeline
    db = CalendarDatabase(tmp_path / "db.sqlite")
    class Context:
        def __enter__(self): return object()
        def __exit__(self, *_args): pass
    monkeypatch.setattr(pipeline, "bootstrap", lambda *_args: 0)
    monkeypatch.setattr(pipeline, "CalendarBrowser", lambda *_args: Context())
    monkeypatch.setattr(pipeline, "sync_months", lambda *_args: [])
    monkeypatch.setattr(pipeline, "update", lambda _db: 0)
    monkeypatch.setattr(pipeline, "validate", lambda *_args, **_kwargs: ({}, ["bad data"]))
    monkeypatch.setattr(db, "export", lambda *_args: {})
    called = []
    monkeypatch.setattr(excel, "export_yearly_excel", lambda *_args: called.append(True))
    with pytest.raises(SourceError, match="validation failed"):
        sync(db, yearly_excel_dir=tmp_path / "excel")
    assert called == []
