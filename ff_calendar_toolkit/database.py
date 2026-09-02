"""Canonical SQLite storage and deterministic exports."""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .ingest import enhanced_natural_identity

FIELDS = [
    "event_key", "source_event_id", "event_name", "event_name_normalized", "currency",
    "impact_color", "impact_level", "date_et", "time_et", "datetime_et", "datetime_utc",
    "all_day", "actual", "forecast", "previous", "source_url", "source_type",
    "source_period", "first_seen_at", "last_seen_at", "scraped_at", "raw_impact",
    "raw_date", "raw_time",
]
ESSENTIAL = ("event_key", "event_name", "event_name_normalized", "currency", "impact_color", "impact_level", "date_et")


class CalendarDatabase:
    def __init__(self, path: Path | str = "data/forex_factory.sqlite") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS events (
          event_key TEXT PRIMARY KEY, source_event_id TEXT, event_name TEXT NOT NULL,
          event_name_normalized TEXT NOT NULL, currency TEXT NOT NULL, impact_color TEXT NOT NULL,
          impact_level TEXT NOT NULL, date_et TEXT NOT NULL, time_et TEXT, datetime_et TEXT,
          datetime_utc TEXT, all_day INTEGER NOT NULL DEFAULT 0, actual TEXT, forecast TEXT,
          previous TEXT, source_url TEXT, source_type TEXT NOT NULL, source_period TEXT,
          first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, scraped_at TEXT NOT NULL,
          raw_impact TEXT, raw_date TEXT, raw_time TEXT
        );
        CREATE INDEX IF NOT EXISTS events_date ON events(date_et);
        CREATE UNIQUE INDEX IF NOT EXISTS events_source_id ON events(source_event_id)
          WHERE source_event_id IS NOT NULL AND source_event_id != '';
        CREATE TABLE IF NOT EXISTS periods (
          period TEXT PRIMARY KEY, status TEXT NOT NULL, event_count INTEGER NOT NULL DEFAULT 0,
          attempted_at TEXT NOT NULL, error TEXT, source_type TEXT
        );
        CREATE TABLE IF NOT EXISTS event_sources (
          provenance_key TEXT PRIMARY KEY, event_key TEXT NOT NULL,
          source_type TEXT NOT NULL, source_event_id TEXT, source_url TEXT,
          source_period TEXT, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
          FOREIGN KEY(event_key) REFERENCES events(event_key) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS event_sources_event ON event_sources(event_key);
        CREATE INDEX IF NOT EXISTS event_sources_type ON event_sources(source_type, event_key);
        """)
        # Backfill normalized provenance when opening a database created by an
        # earlier toolkit version. INSERT OR IGNORE makes this migration safe on
        # every startup.
        for event in self.connection.execute(
            "SELECT event_key,source_type,source_event_id,source_url,source_period,"
            "first_seen_at,last_seen_at FROM events"
        ).fetchall():
            self._record_source(dict(event))
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def upsert(self, records: Iterable[dict]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        with self.connection:
            for item in records:
                row = {key: item.get(key) for key in FIELDS}
                row["first_seen_at"] = row["first_seen_at"] or now
                row["last_seen_at"] = row["last_seen_at"] or now
                row["scraped_at"] = row["scraped_at"] or now
                row["all_day"] = int(bool(row["all_day"]))
                provenance_row = row.copy()
                existing_by_source_id = None
                if row["source_event_id"]:
                    existing_by_source_id = self.connection.execute(
                        "SELECT * FROM events WHERE source_event_id=?",
                        (row["source_event_id"],),
                    ).fetchone()
                    if (existing_by_source_id
                            and existing_by_source_id["event_key"] != row["event_key"]):
                        # The upstream ID is authoritative even when the
                        # schedule/name changed. Canonicalize its legacy key
                        # before considering the incoming natural identity.
                        self._merge_event(existing_by_source_id["event_key"],
                                          row["event_key"], row)
                    if existing_by_source_id:
                        existing_by_source_id = self.connection.execute(
                            "SELECT * FROM events WHERE event_key=?", (row["event_key"],)
                        ).fetchone()
                existing = existing_by_source_id
                identity_matches = self._identity_matches(row)
                stable_matches = [candidate for candidate in identity_matches
                                  if candidate["source_event_id"]]
                derived_matches = [candidate for candidate in identity_matches
                                   if not candidate["source_event_id"]
                                   and candidate["event_key"].startswith("derived:")]
                stable_ids = {candidate["source_event_id"] for candidate in stable_matches}
                if row["source_event_id"]:
                    stable_ids.add(row["source_event_id"])
                if row["source_event_id"] and len(stable_ids) == 1:
                    # A sole stable identity is authoritative. Promote every
                    # matching legacy row; row count does not create ambiguity.
                    for candidate in stable_matches + derived_matches:
                        if candidate["event_key"] != row["event_key"]:
                            self._merge_event(candidate["event_key"], row["event_key"], row)
                    if existing_by_source_id is None:
                        existing = self.connection.execute(
                            "SELECT event_key,first_seen_at FROM events WHERE event_key=?",
                            (row["event_key"],),
                        ).fetchone()
                elif not row["source_event_id"] and len(stable_ids) == 1:
                    source_id = next(iter(stable_ids))
                    stable_key = f"ff:{source_id}"
                    canonical_match = next((candidate for candidate in stable_matches
                                            if candidate["event_key"] == stable_key), None)
                    if canonical_match is None:
                        # Some legacy databases attached an upstream ID without
                        # rekeying the event. Promote it before applying this
                        # no-ID observation rather than assuming ff:<id> exists.
                        self._merge_event(stable_matches[0]["event_key"], stable_key)
                    for candidate in stable_matches:
                        if candidate["event_key"] != stable_key:
                            self._merge_event(candidate["event_key"], stable_key)
                    existing = self.connection.execute(
                        "SELECT event_key,first_seen_at FROM events WHERE event_key=?",
                        (stable_key,),
                    ).fetchone()
                if existing is None:
                    existing = self.connection.execute(
                        "SELECT event_key,first_seen_at FROM events WHERE event_key=?",
                        (row["event_key"],),
                    ).fetchone()
                if existing and existing["event_key"] != row["event_key"]:
                    # IDs are stable even when time/name (and hence fallback key) changes.
                    row["event_key"] = existing["event_key"]
                    provenance_row["event_key"] = existing["event_key"]
                    if not provenance_row["source_event_id"]:
                        # A no-ID observation may refresh values but cannot
                        # replace the stable record's identity/source fields.
                        canonical_existing = self.connection.execute(
                            "SELECT * FROM events WHERE event_key=?", (row["event_key"],)
                        ).fetchone()
                        if canonical_existing:
                            for field in ("source_event_id", "event_name", "event_name_normalized",
                                          "currency", "date_et", "time_et", "datetime_et",
                                          "datetime_utc", "all_day", "source_url", "source_type",
                                          "source_period", "raw_date", "raw_time"):
                                row[field] = canonical_existing[field]
                has_monthly = bool(existing and self.connection.execute(
                    "SELECT 1 FROM event_sources WHERE event_key=? AND source_type='calendar_html' LIMIT 1",
                    (row["event_key"],),
                ).fetchone())
                columns = ",".join(FIELDS)
                placeholders = ",".join("?" for _ in FIELDS)
                value_fields = {"actual", "forecast", "previous"}
                updates = ",".join(
                    (f"{f}=CASE WHEN NULLIF(excluded.{f},'') IS NOT NULL "
                     f"AND (NULLIF(events.{f},'') IS NULL OR excluded.scraped_at>=events.scraped_at) "
                     f"THEN excluded.{f} ELSE events.{f} END" if f in value_fields
                     else f"{f}=MAX(events.{f},excluded.{f})" if f in {"last_seen_at", "scraped_at"}
                     else f"{f}=excluded.{f}")
                    for f in FIELDS if f not in {"event_key", "first_seen_at"}
                )
                if row["source_type"] == "huggingface_archive" and has_monthly:
                    # Archive provenance remains authoritative for archive
                    # coverage, but must not erase the richer monthly ID/source.
                    self.connection.execute(
                        "UPDATE events SET last_seen_at=?,scraped_at=? WHERE event_key=?",
                        (row["last_seen_at"], row["scraped_at"], row["event_key"]),
                    )
                else:
                    self.connection.execute(
                        f"INSERT INTO events ({columns}) VALUES ({placeholders}) "
                        f"ON CONFLICT(event_key) DO UPDATE SET {updates}",
                        [row[f] for f in FIELDS],
                    )
                self._record_source(provenance_row)
                count += 1
        return count

    def _identity_matches(self, row: dict) -> list[sqlite3.Row]:
        identity = enhanced_natural_identity(row)
        candidates = self.connection.execute(
            "SELECT * FROM events WHERE date_et=? AND currency=? AND event_name_normalized=? "
            "AND COALESCE(time_et,'')=?",
            (identity[0], identity[3], identity[4], identity[1]),
        )
        return [candidate for candidate in candidates
                if enhanced_natural_identity(dict(candidate)) == identity]

    @staticmethod
    def _latest_nonempty(stable: dict, derived: dict, field: str):
        left, right = stable.get(field), derived.get(field)
        if right not in (None, "") and (left in (None, "") or
                str(derived.get("scraped_at") or "") > str(stable.get("scraped_at") or "")):
            return right
        return left

    def _merge_event(self, derived_key: str, stable_key: str, stable_row: dict | None = None) -> None:
        """Merge one derived event into a stable event inside the caller's transaction."""
        derived_record = self.connection.execute(
            "SELECT * FROM events WHERE event_key=?", (derived_key,)
        ).fetchone()
        if not derived_record:
            return
        derived = dict(derived_record)
        current = self.connection.execute(
            "SELECT * FROM events WHERE event_key=?", (stable_key,)
        ).fetchone()
        stable = dict(current) if current else dict(stable_row or {})
        if not current and not stable_row:
            stable = dict(derived)
        stable.update({"event_key": stable_key})
        for field in FIELDS:
            stable.setdefault(field, derived.get(field))
        for field in ("actual", "forecast", "previous"):
            stable[field] = self._latest_nonempty(stable, derived, field)
        stable["first_seen_at"] = min(filter(None, (stable.get("first_seen_at"), derived.get("first_seen_at"))))
        stable["last_seen_at"] = max(filter(None, (stable.get("last_seen_at"), derived.get("last_seen_at"))))
        stable["scraped_at"] = max(filter(None, (stable.get("scraped_at"), derived.get("scraped_at"))))
        sources = [dict(source) for source in self.connection.execute(
            "SELECT * FROM event_sources WHERE event_key=?", (derived_key,)
        )]
        # Delete the old identity before inserting its canonical ff: key. This
        # ordering is required when the unique source-ID index is enabled.
        self.connection.execute("DELETE FROM event_sources WHERE event_key=?", (derived_key,))
        self.connection.execute("DELETE FROM events WHERE event_key=?", (derived_key,))
        columns = ",".join(FIELDS)
        updates = ",".join(f"{field}=excluded.{field}" for field in FIELDS
                           if field != "event_key")
        self.connection.execute(
            f"INSERT INTO events ({columns}) VALUES ({','.join('?' for _ in FIELDS)}) "
            f"ON CONFLICT(event_key) DO UPDATE SET {updates}",
            [stable.get(field) for field in FIELDS],
        )
        for source in sources:
            source["event_key"] = stable_key
            self._record_source(source)

    def identity_collisions(self) -> dict:
        groups: dict[tuple, list[dict]] = {}
        for row in self.rows():
            groups.setdefault(enhanced_natural_identity(row), []).append(row)
        mixed, ambiguous = [], []
        for identity, records in groups.items():
            derived = [r for r in records if not r["source_event_id"]]
            stable = [r for r in records if r["source_event_id"]]
            noncanonical_stable = [r for r in stable
                                   if r["event_key"] != f"ff:{r['source_event_id']}"]
            if stable and (derived or noncanonical_stable):
                source_ids = sorted({r["source_event_id"] for r in stable})
                entry = {"identity": identity, "derived": derived, "stable": stable,
                         "source_event_ids": source_ids}
                (mixed if len(source_ids) == 1 else ambiguous).append(entry)
        return {"candidates": mixed, "ambiguous": ambiguous}

    def repair_identities(self, apply: bool = False, backup_directory: Path | str = "data/backups") -> dict:
        collisions = self.identity_collisions()
        all_groups = collisions["candidates"] + collisions["ambiguous"]
        by_year: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for group in all_groups:
            year = group["identity"][0][:4]
            by_year[year] = by_year.get(year, 0) + 1
            for source in {r["source_type"] for r in group["derived"] + group["stable"]}:
                by_source[source] = by_source.get(source, 0) + 1
        report = {"dry_run": not apply, "candidate_groups": len(collisions["candidates"]),
                  "ambiguous_groups": len(collisions["ambiguous"]),
                  "counts_by_year": dict(sorted(by_year.items())),
                  "counts_by_source_type": dict(sorted(by_source.items())),
                  "examples": [{"identity": list(g["identity"]),
                                "event_keys": [r["event_key"] for r in g["derived"] + g["stable"]]}
                               for g in all_groups[:10]],
                  "ambiguous_examples": [{"identity": list(g["identity"]),
                                "event_keys": [r["event_key"] for r in g["derived"] + g["stable"]]}
                               for g in collisions["ambiguous"][:10]],
                  "repaired_groups": 0, "backup": None}
        if not apply or not collisions["candidates"]:
            return report
        backup_directory = Path(backup_directory); backup_directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = backup_directory / f"forex_factory-before-identity-repair-{stamp}.sqlite"
        destination = sqlite3.connect(backup)
        try:
            self.connection.backup(destination)
        finally:
            destination.close()
        report["backup"] = str(backup)
        with self.connection:
            for group in collisions["candidates"]:
                stable_key = f"ff:{group['source_event_ids'][0]}"
                canonical = next((row for row in group["stable"]
                                  if row["event_key"] == stable_key), None)
                if canonical is None:
                    promote = group["stable"][0]
                    self._merge_event(promote["event_key"], stable_key)
                for stable in group["stable"]:
                    if stable["event_key"] != stable_key:
                        self._merge_event(stable["event_key"], stable_key)
                for derived in group["derived"]:
                    self._merge_event(derived["event_key"], stable_key)
                report["repaired_groups"] += 1
        return report

    def _record_source(self, row: dict) -> None:
        identity = "|".join(str(row.get(key) or "") for key in (
            "event_key", "source_type", "source_event_id", "source_url", "source_period"
        ))
        provenance_key = hashlib.sha256(identity.encode()).hexdigest()
        first = row.get("first_seen_at") or datetime.now(timezone.utc).isoformat()
        last = row.get("last_seen_at") or first
        self.connection.execute(
            "INSERT INTO event_sources VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(provenance_key) DO UPDATE SET "
            "first_seen_at=MIN(event_sources.first_seen_at,excluded.first_seen_at),"
            "last_seen_at=MAX(event_sources.last_seen_at,excluded.last_seen_at)",
            (provenance_key, row["event_key"], row["source_type"], row.get("source_event_id"),
             row.get("source_url"), row.get("source_period"), first, last),
        )

    def sources(self, event_key: str) -> list[dict]:
        """Return all normalized provenance records for a canonical event."""
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM event_sources WHERE event_key=? ORDER BY source_type,provenance_key",
            (event_key,),
        )]

    def mark_period(self, period: str, status: str, count: int = 0, error: str | None = None,
                    source_type: str | None = None) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO periods VALUES (?,?,?,?,?,?) ON CONFLICT(period) DO UPDATE SET "
                "status=excluded.status,event_count=excluded.event_count,attempted_at=excluded.attempted_at,"
                "error=excluded.error,source_type=excluded.source_type",
                (period, status, count, datetime.now(timezone.utc).isoformat(), error, source_type),
            )

    def rows(self) -> list[dict]:
        return [dict(r) for r in self.connection.execute(
            "SELECT * FROM events ORDER BY date_et, COALESCE(time_et,''), currency, event_name_normalized, event_key"
        )]

    def export(self, formats: Iterable[str], directory: Path | str = "data/exports") -> dict[str, str]:
        directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
        rows = self.rows(); hashes = {}
        for fmt in formats:
            path = directory / f"forex_factory_calendar_full.{fmt}"
            if fmt == "csv":
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
                    writer.writeheader(); writer.writerows(rows)
            elif fmt == "parquet":
                try:
                    import pandas as pd
                    pd.DataFrame(rows, columns=FIELDS).to_parquet(path, index=False)
                except ImportError as exc:
                    raise RuntimeError("Parquet export requires pandas and pyarrow") from exc
            else:
                raise ValueError(f"unsupported export format: {fmt}")
            hashes[fmt] = hashlib.sha256(path.read_bytes()).hexdigest()
        return hashes
