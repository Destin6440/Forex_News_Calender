"""Canonical SQLite storage and deterministic exports."""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

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
        """)

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
                existing = None
                if row["source_event_id"]:
                    existing = self.connection.execute(
                        "SELECT event_key, first_seen_at FROM events WHERE source_event_id=?",
                        (row["source_event_id"],),
                    ).fetchone()
                if existing and existing["event_key"] != row["event_key"]:
                    # IDs are stable even when time/name (and hence fallback key) changes.
                    row["event_key"] = existing["event_key"]
                columns = ",".join(FIELDS)
                placeholders = ",".join("?" for _ in FIELDS)
                updates = ",".join(f"{f}=excluded.{f}" for f in FIELDS if f not in {"event_key", "first_seen_at"})
                self.connection.execute(
                    f"INSERT INTO events ({columns}) VALUES ({placeholders}) "
                    f"ON CONFLICT(event_key) DO UPDATE SET {updates}",
                    [row[f] for f in FIELDS],
                )
                count += 1
        return count

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
