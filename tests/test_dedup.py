from datetime import datetime, timedelta, timezone

from ff_calendar_toolkit.dedup import SeenStore, _normalize_title, make_hash


def test_normalize_collapses_whitespace_and_case_and_punct():
    assert _normalize_title("Hello, World!") == _normalize_title("hello world")
    assert _normalize_title("  USD  CPI   m/m") == _normalize_title("usd cpi m m")


def test_make_hash_ignores_source_and_normalizes():
    assert make_hash("Fed Hikes Rates 25bps.") == make_hash("fed hikes rates 25bps")


def test_check_and_mark_first_is_new_subsequent_are_not(tmp_path):
    store = SeenStore(tmp_path / "seen.db")
    assert store.check_and_mark("forexfactory", "Core CPI m/m") is True
    assert store.check_and_mark("forexfactory", "Core CPI m/m") is False
    assert store.count() == 1


def test_cross_source_same_title_dedups(tmp_path):
    store = SeenStore(tmp_path / "seen.db")
    assert store.check_and_mark("yahoo", "ECB Holds Rates Steady") is True
    # bloomberg sees same title 30s later → must be deduped
    assert store.check_and_mark("bloomberg", "ECB Holds Rates Steady") is False
    assert store.count() == 1


def test_is_seen_after_mark(tmp_path):
    store = SeenStore(tmp_path / "seen.db")
    assert store.is_seen("X") is False
    store.check_and_mark("ff", "X")
    assert store.is_seen("X") is True


def test_ttl_prune_drops_old_entries(tmp_path):
    db = tmp_path / "seen.db"
    store = SeenStore(db, ttl_days=7)
    store.check_and_mark("ff", "Old News")
    # rewrite the row's timestamp to 30 days ago
    old_iso = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    store._conn.execute("UPDATE seen SET first_seen_at = ?", (old_iso,))
    store.close()

    # re-open → prune runs in __init__
    store2 = SeenStore(db, ttl_days=7)
    assert store2.count() == 0


def test_context_manager_closes(tmp_path):
    with SeenStore(tmp_path / "seen.db") as store:
        assert store.check_and_mark("ff", "Y") is True
