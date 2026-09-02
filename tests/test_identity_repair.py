import sqlite3
from pathlib import Path

import pytest

from ff_calendar_toolkit.database import CalendarDatabase, FIELDS
from ff_calendar_toolkit.excel_export import export_yearly_excel
from ff_calendar_toolkit.ingest import canonical, enhanced_natural_identity
from ff_calendar_toolkit.pipeline import validate


def event(source_id=None, source_type="calendar_html", raw_time="8:30am", **values):
    raw = {"date": values.pop("date", "2026-01-01"), "time": raw_time,
           "currency": values.pop("currency", "USD"), "event": values.pop("name", "Bank Holiday"),
           "impact": "gray", **values}
    if source_id is not None:
        raw["source_event_id"] = source_id
    return canonical(raw, source_type, "2026-01")


def force_insert(db, row):
    db.connection.execute(
        f"INSERT INTO events ({','.join(FIELDS)}) VALUES ({','.join('?' for _ in FIELDS)})",
        [row.get(field) for field in FIELDS],
    )
    db._record_source(row)
    db.connection.commit()


def distinct_derived(suffix, source_type="calendar_html", **values):
    row = event(source_type=source_type, **values)
    row["event_key"] = f"derived:test-{suffix}"
    row["source_period"] = f"legacy-{suffix}"
    return row


def noncanonical_stable(source_id="42", suffix="legacy", **values):
    row = event(source_id, **values)
    row["event_key"] = f"derived:stable-{suffix}"
    row["source_period"] = f"stable-{suffix}"
    return row


def test_derived_then_stable_promotes_key_and_preserves_provenance(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    derived = event(); derived["first_seen_at"] = "2026-01-01T00:00:00+00:00"
    stable = event("146482"); stable["first_seen_at"] = "2026-01-02T00:00:00+00:00"
    db.upsert([derived]); db.upsert([stable])
    assert [row["event_key"] for row in db.rows()] == ["ff:146482"]
    assert {source["source_type"] for source in db.sources("ff:146482")} == {"calendar_html"}
    assert len(db.sources("ff:146482")) == 2
    assert db.rows()[0]["first_seen_at"] == "2026-01-01T00:00:00+00:00"


def test_stable_then_derived_updates_canonical_and_attaches_provenance(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    stable = event("146482", actual="1")
    derived = event(source_type="weekly_json", actual="2")
    db.upsert([stable]); db.upsert([derived])
    [row] = db.rows()
    assert row["event_key"] == "ff:146482" and row["source_event_id"] == "146482"
    assert row["actual"] == "2"
    assert {source["source_type"] for source in db.sources(row["event_key"])} == {"calendar_html", "weekly_json"}


def test_weekly_derived_then_calendar_stable_reconciles(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    db.upsert([event(source_type="weekly_json"), event("99", source_type="calendar_html")])
    assert len(db.rows()) == 1
    assert {s["source_type"] for s in db.sources("ff:99")} == {"weekly_json", "calendar_html"}


def test_incoming_sole_stable_id_promotes_all_matching_derived_rows(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    force_insert(db, distinct_derived("html"))
    force_insert(db, distinct_derived("weekly", source_type="weekly_json"))

    db.upsert([event("99")])

    assert [row["event_key"] for row in db.rows()] == ["ff:99"]
    assert len(db.sources("ff:99")) == 3


def test_repair_preserves_timestamps_values_and_is_idempotent(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    derived = event(actual="new actual", forecast="new forecast", previous="new previous")
    stable = event("42", actual="old actual", forecast="", previous=None)
    derived.update(first_seen_at="2025-01-01", last_seen_at="2026-03-01", scraped_at="2026-03-01")
    stable.update(first_seen_at="2025-02-01", last_seen_at="2026-02-01", scraped_at="2026-02-01")
    force_insert(db, derived); force_insert(db, stable)
    report = db.repair_identities(apply=True, backup_directory=tmp_path / "backups")
    [row] = db.rows()
    assert report["repaired_groups"] == 1 and Path(report["backup"]).exists()
    assert (row["first_seen_at"], row["last_seen_at"], row["scraped_at"]) == ("2025-01-01", "2026-03-01", "2026-03-01")
    assert (row["actual"], row["forecast"], row["previous"]) == ("new actual", "new forecast", "new previous")
    second = db.repair_identities(apply=True, backup_directory=tmp_path / "backups")
    assert second["repaired_groups"] == 0 and second["backup"] is None


def test_one_stable_target_merges_two_derived_rows(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    first = distinct_derived("first", actual="older")
    second = distinct_derived("second", source_type="weekly_json", actual="newest")
    first.update(first_seen_at="2025-01-01", last_seen_at="2026-01-01", scraped_at="2026-01-01")
    second.update(first_seen_at="2025-02-01", last_seen_at="2026-03-01", scraped_at="2026-03-01")
    stable = event("42", actual="stable")
    stable.update(first_seen_at="2025-03-01", last_seen_at="2026-02-01", scraped_at="2026-02-01")
    for row in (first, second, stable):
        force_insert(db, row)

    report = db.repair_identities(apply=True, backup_directory=tmp_path / "backups")

    assert report["candidate_groups"] == report["repaired_groups"] == 1
    assert [row["event_key"] for row in db.rows()] == ["ff:42"]
    assert db.rows()[0]["actual"] == "newest"
    assert db.rows()[0]["first_seen_at"] == "2025-01-01"
    assert db.rows()[0]["last_seen_at"] == "2026-03-01"
    assert len(db.sources("ff:42")) == 3
    assert db.repair_identities(apply=True, backup_directory=tmp_path / "backups")["repaired_groups"] == 0


def test_repeated_rows_with_same_stable_id_are_not_ambiguous(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    db.connection.execute("DROP INDEX events_source_id")
    force_insert(db, distinct_derived("legacy"))
    force_insert(db, event("42"))
    duplicate = event("42", source_type="weekly_json")
    duplicate["event_key"] = "ff:42-duplicate"
    force_insert(db, duplicate)

    collisions = db.identity_collisions()

    assert len(collisions["candidates"]) == 1
    assert collisions["candidates"][0]["source_event_ids"] == ["42"]
    assert collisions["ambiguous"] == []

    report = db.repair_identities(apply=True, backup_directory=tmp_path / "backups")
    assert report["repaired_groups"] == 1
    assert [row["event_key"] for row in db.rows()] == ["ff:42"]


def test_noncanonical_source_id_row_promotes_with_unique_index_and_preserves_data(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    identified = noncanonical_stable(actual="stable actual", forecast="stable forecast")
    identified.update(first_seen_at="2025-02-01", last_seen_at="2026-02-01", scraped_at="2026-02-01")
    unidentified = distinct_derived("no-id", source_type="weekly_json", previous="new previous")
    unidentified.update(first_seen_at="2025-01-01", last_seen_at="2026-03-01", scraped_at="2026-03-01")
    force_insert(db, identified)
    force_insert(db, unidentified)

    report = db.repair_identities(apply=True, backup_directory=tmp_path / "backups")

    [row] = db.rows()
    assert row["event_key"] == "ff:42" and row["source_event_id"] == "42"
    assert row["source_type"] == identified["source_type"]
    assert (row["actual"], row["forecast"], row["previous"]) == (
        "stable actual", "stable forecast", "new previous")
    assert (row["first_seen_at"], row["last_seen_at"], row["scraped_at"]) == (
        "2025-01-01", "2026-03-01", "2026-03-01")
    assert len(db.sources("ff:42")) == 2
    assert validate(db, strict=True, write_manifest=False)[0]["mixed_derived_stable_identity_collisions"] == 0
    assert report["repaired_groups"] == 1
    assert db.repair_identities(apply=True, backup_directory=tmp_path / "backups")["repaired_groups"] == 0


def test_no_id_upsert_promotes_noncanonical_source_id_without_crashing(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    force_insert(db, noncanonical_stable(actual="old"))

    db.upsert([event(source_type="weekly_json", actual="new")])

    [row] = db.rows()
    assert row["event_key"] == "ff:42" and row["source_event_id"] == "42"
    assert row["actual"] == "new"
    assert len(db.sources("ff:42")) == 2


def test_source_id_revision_promotes_noncanonical_key_independent_of_identity(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    original = noncanonical_stable(actual="old")
    force_insert(db, original)
    revised = event("42", raw_time="9:45am", name="Renamed Bank Holiday", actual="new")

    db.upsert([revised])

    [row] = db.rows()
    assert row["event_key"] == "ff:42" and row["source_event_id"] == "42"
    assert (row["time_et"], row["event_name"], row["actual"]) == (
        "09:45", "Renamed Bank Holiday", "new")
    assert len(db.sources("ff:42")) == 2


def test_archive_all_day_and_calendar_month_data_remain_distinct(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    db.upsert([event(source_type="huggingface_archive", raw_time="All Day")])
    db.upsert([event(source_type="calendar_html", raw_time="Feb Data")])

    assert len(db.rows()) == 2
    assert {row["raw_time"] for row in db.rows()} == {"All Day", "Feb Data"}


def test_two_stable_ids_and_no_id_calendar_observation_remain_separate(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    db.upsert([event("1"), event("2")])

    db.upsert([event(source_type="calendar_html")])

    assert len(db.rows()) == 3
    assert {row["source_event_id"] for row in db.rows()} == {None, "1", "2"}


def test_third_stable_id_does_not_absorb_existing_stable_ids(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    db.upsert([event("1"), event("2")])

    db.upsert([event("3")])

    assert len(db.rows()) == 3
    assert {row["source_event_id"] for row in db.rows()} == {"1", "2", "3"}


def test_clock_archive_and_calendar_overlap_reconciles_by_enhanced_identity(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    db.upsert([event(source_type="huggingface_archive")])

    db.upsert([event("42", source_type="calendar_html")])

    assert [row["event_key"] for row in db.rows()] == ["ff:42"]
    assert {source["source_type"] for source in db.sources("ff:42")} == {
        "huggingface_archive", "calendar_html"}


def test_ambiguous_and_distinct_source_ids_are_not_merged(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    force_insert(db, event())
    force_insert(db, event("1")); force_insert(db, event("2"))
    report = db.repair_identities(apply=True, backup_directory=tmp_path / "backups")
    assert report["ambiguous_groups"] == 1 and report["repaired_groups"] == 0
    assert len(db.rows()) == 3
    # Once the derived row is absent, equal identities with distinct IDs are legitimate.
    db.connection.execute("DELETE FROM event_sources WHERE event_key LIKE 'derived:%'")
    db.connection.execute("DELETE FROM events WHERE event_key LIKE 'derived:%'"); db.connection.commit()
    assert db.identity_collisions() == {"candidates": [], "ambiguous": []}


@pytest.mark.parametrize("left,right", [("Feb Data", "Mar Data"), ("Sep 27th", "Oct 4th"), ("7th-14th", "23rd-1st")])
def test_clockless_period_identities_remain_distinct(left, right):
    assert enhanced_natural_identity(event(raw_time=left)) != enhanced_natural_identity(event(raw_time=right))


def test_strict_validation_and_excel_are_clean_after_repair(tmp_path):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    force_insert(db, event()); force_insert(db, event("42"))
    manifest, errors = validate(db, strict=True, write_manifest=False)
    assert manifest["mixed_derived_stable_identity_collisions"] == 1
    assert any("natural-identity collisions" in error for error in errors)
    db.repair_identities(apply=True, backup_directory=tmp_path / "backups")
    manifest, _ = validate(db, strict=False, write_manifest=False)
    assert manifest["mixed_derived_stable_identity_collisions"] == 0
    paths = export_yearly_excel(db, tmp_path / "excel", manifest)
    assert [path.name for path in paths] == ["Forex_Factory_News_2026.xlsx"]


def test_repair_rolls_back_multi_derived_events_and_sources_on_failure(tmp_path, monkeypatch):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    force_insert(db, distinct_derived("first"))
    force_insert(db, distinct_derived("second", source_type="weekly_json"))
    force_insert(db, event("42"))
    before_events = [dict(row) for row in db.connection.execute("SELECT * FROM events ORDER BY event_key")]
    before_sources = [dict(row) for row in db.connection.execute("SELECT * FROM event_sources ORDER BY provenance_key")]
    original = db._merge_event
    calls = 0
    def fail_second(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected failure")
        original(*args)
    monkeypatch.setattr(db, "_merge_event", fail_second)
    with pytest.raises(RuntimeError, match="injected"):
        db.repair_identities(apply=True, backup_directory=tmp_path / "backups")
    assert [dict(row) for row in db.connection.execute("SELECT * FROM events ORDER BY event_key")] == before_events
    assert [dict(row) for row in db.connection.execute("SELECT * FROM event_sources ORDER BY provenance_key")] == before_sources


def test_repair_rolls_back_noncanonical_promotion_on_failure(tmp_path, monkeypatch):
    db = CalendarDatabase(tmp_path / "db.sqlite")
    force_insert(db, noncanonical_stable())
    force_insert(db, distinct_derived("no-id"))
    before_events = [dict(row) for row in db.connection.execute("SELECT * FROM events ORDER BY event_key")]
    before_sources = [dict(row) for row in db.connection.execute("SELECT * FROM event_sources ORDER BY provenance_key")]
    original = db._record_source
    calls = 0
    def fail_during_promotion(row):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("promotion failure")
        original(row)
    monkeypatch.setattr(db, "_record_source", fail_during_promotion)

    with pytest.raises(RuntimeError, match="promotion failure"):
        db.repair_identities(apply=True, backup_directory=tmp_path / "backups")

    assert [dict(row) for row in db.connection.execute("SELECT * FROM events ORDER BY event_key")] == before_events
    assert [dict(row) for row in db.connection.execute("SELECT * FROM event_sources ORDER BY provenance_key")] == before_sources
