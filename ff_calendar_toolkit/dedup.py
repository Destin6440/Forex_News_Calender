"""Cross-source news-item dedup using SQLite.

Three sources (FF, Yahoo, Bloomberg-via-GDELT/GNews) regularly republish the same
macro story within minutes. A title-hash table prevents Telegram fanout from spamming
the same item. Keyed by SHA-256 of (normalized title + source).
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_TTL_DAYS = 7

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def _normalize_title(title: str) -> str:
    lowered = title.casefold().strip()
    stripped = _PUNCT_RE.sub(" ", lowered)
    return _WS_RE.sub(" ", stripped).strip()


def make_hash(title: str) -> str:
    """Hash the normalized title only — cross-source dedup is the goal."""
    return hashlib.sha256(_normalize_title(title).encode("utf-8")).hexdigest()


class SeenStore:
    def __init__(self, db_path: Path, ttl_days: int = DEFAULT_TTL_DAYS) -> None:
        self.db_path = db_path
        self.ttl_days = ttl_days
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen (
                hash TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                first_seen_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_first_seen ON seen(first_seen_at)")
        self._prune()

    def _prune(self) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.ttl_days)).isoformat()
        cur = self._conn.execute("DELETE FROM seen WHERE first_seen_at < ?", (cutoff,))
        return cur.rowcount or 0

    def check_and_mark(self, source: str, title: str) -> bool:
        """Insert if new. Returns True when this is the first time we see the title.

        `source` is recorded for the first sighting only; subsequent calls from other
        sources collide on the title hash and return False.
        """
        h = make_hash(title)
        now_iso = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO seen(hash, source, title, first_seen_at) VALUES (?, ?, ?, ?)",
            (h, source, title, now_iso),
        )
        return cur.rowcount == 1

    def is_seen(self, title: str) -> bool:
        h = make_hash(title)
        row = self._conn.execute("SELECT 1 FROM seen WHERE hash = ?", (h,)).fetchone()
        return row is not None

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM seen").fetchone()
        return int(row[0])

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SeenStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
