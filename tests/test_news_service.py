from dataclasses import dataclass
from pathlib import Path

import pytest

from ff_calendar_toolkit.analyzer import AnalysisResult, AnalyzerError
from ff_calendar_toolkit.console import AppConsole
from ff_calendar_toolkit.dedup import SeenStore
from ff_calendar_toolkit.models import NewsItem
from ff_calendar_toolkit.news_service import (
    NewsService,
    NewsServiceOptions,
    _format_analysis,
    _format_raw,
)
from ff_calendar_toolkit.telegram import TelegramError, TelegramSender


class FakeTelegram:
    def __init__(self, fail_for: set[str] | None = None):
        self.sent: list[tuple[str, str]] = []
        self.fail_for = fail_for or set()

    def send(self, chat_id: str, text: str, parse_mode=None) -> None:
        if chat_id in self.fail_for:
            raise TelegramError("simulated failure")
        self.sent.append((chat_id, text))


def _make_options(tmp_path: Path, **overrides) -> NewsServiceOptions:
    defaults = dict(
        yahoo_tickers=("AAPL",),
        bloomberg_keywords=("forex",),
        raw_chat_id="RAW",
        analysis_chat_id="ANL",
        dedup_db_path=tmp_path / "seen.db",
        dedup_ttl_days=7,
        analysis_confidence_threshold=0.5,
        enable_analysis=True,
        analysis_workers=2,
    )
    defaults.update(overrides)
    return NewsServiceOptions(**defaults)


def _item(title: str, source: str = "yahoo") -> NewsItem:
    return NewsItem(
        source=source,
        title=title,
        url=f"https://x/{abs(hash(title))}",
        published_at="2026-05-23T20:00:00+00:00",
    )


def _result(confidence: float, sentiment: float = -0.5) -> AnalysisResult:
    return AnalysisResult(
        sentiment=sentiment,
        affected_pairs=("EURUSD",),
        time_horizon="short",
        confidence=confidence,
        summary="test",
    )


def test_run_posts_raw_and_dedups_across_runs(tmp_path):
    opts = _make_options(tmp_path, enable_analysis=False)
    tg = FakeTelegram()

    with SeenStore(opts.dedup_db_path) as seen:
        svc = NewsService(
            opts, tg, seen, console=AppConsole(),
            fetch_yahoo=lambda tickers, on_error=None: [_item("A"), _item("B")],
            fetch_bloomberg=lambda keywords, on_error=None: [_item("C", "bloomberg")],
        )
        stats = svc.run()

    assert stats.fetched == 3
    assert stats.new_after_dedup == 3
    assert stats.raw_posted == 3
    assert all(chat == "RAW" for chat, _ in tg.sent)

    # second run: same items → all deduped
    tg2 = FakeTelegram()
    with SeenStore(opts.dedup_db_path) as seen:
        svc = NewsService(
            opts, tg2, seen, console=AppConsole(),
            fetch_yahoo=lambda tickers, on_error=None: [_item("A"), _item("B")],
            fetch_bloomberg=lambda keywords, on_error=None: [_item("C", "bloomberg")],
        )
        stats = svc.run()

    assert stats.fetched == 3
    assert stats.new_after_dedup == 0
    assert tg2.sent == []


def test_cross_source_same_title_only_posted_once(tmp_path):
    opts = _make_options(tmp_path, enable_analysis=False)
    tg = FakeTelegram()
    with SeenStore(opts.dedup_db_path) as seen:
        NewsService(
            opts, tg, seen, console=AppConsole(),
            fetch_yahoo=lambda tickers, on_error=None: [_item("Fed Pauses", "yahoo")],
            fetch_bloomberg=lambda keywords, on_error=None: [_item("Fed Pauses", "bloomberg")],
        ).run()
    assert len(tg.sent) == 1


def test_analysis_posts_when_above_threshold(tmp_path):
    opts = _make_options(tmp_path, analysis_confidence_threshold=0.5)
    tg = FakeTelegram()
    with SeenStore(opts.dedup_db_path) as seen:
        stats = NewsService(
            opts, tg, seen, console=AppConsole(),
            fetch_yahoo=lambda tickers, on_error=None: [_item("HighConf")],
            fetch_bloomberg=lambda keywords, on_error=None: [],
            analyze_fn=lambda item, cfg=None: _result(confidence=0.9),
            analyzer_config=None,
        ).run()

    raw_msgs = [m for c, m in tg.sent if c == "RAW"]
    analysis_msgs = [m for c, m in tg.sent if c == "ANL"]
    assert len(raw_msgs) == 1
    assert len(analysis_msgs) == 1
    assert stats.analyzed_posted == 1
    assert stats.analysis_below_threshold == 0


def test_analysis_skipped_when_below_threshold(tmp_path):
    opts = _make_options(tmp_path, analysis_confidence_threshold=0.8)
    tg = FakeTelegram()
    with SeenStore(opts.dedup_db_path) as seen:
        stats = NewsService(
            opts, tg, seen, console=AppConsole(),
            fetch_yahoo=lambda tickers, on_error=None: [_item("LowConf")],
            fetch_bloomberg=lambda keywords, on_error=None: [],
            analyze_fn=lambda item, cfg=None: _result(confidence=0.3),
        ).run()

    assert stats.analyzed_posted == 0
    assert stats.analysis_below_threshold == 1
    assert all(chat == "RAW" for chat, _ in tg.sent)


def test_analyzer_error_does_not_block_raw(tmp_path):
    opts = _make_options(tmp_path)
    tg = FakeTelegram()

    def boom(item, cfg=None):
        raise AnalyzerError("LLM down")

    with SeenStore(opts.dedup_db_path) as seen:
        stats = NewsService(
            opts, tg, seen, console=AppConsole(),
            fetch_yahoo=lambda tickers, on_error=None: [_item("X")],
            fetch_bloomberg=lambda keywords, on_error=None: [],
            analyze_fn=boom,
        ).run()

    assert stats.raw_posted == 1
    assert stats.analysis_failed == 1
    assert stats.analyzed_posted == 0


def test_raw_send_failure_recorded_in_stats(tmp_path):
    opts = _make_options(tmp_path, enable_analysis=False)
    tg = FakeTelegram(fail_for={"RAW"})
    with SeenStore(opts.dedup_db_path) as seen:
        stats = NewsService(
            opts, tg, seen, console=AppConsole(),
            fetch_yahoo=lambda tickers, on_error=None: [_item("X"), _item("Y")],
            fetch_bloomberg=lambda keywords, on_error=None: [],
        ).run()
    assert stats.raw_posted == 0
    assert stats.raw_failed == 2
    assert len(stats.errors) == 2


def test_format_raw_includes_source_and_url():
    item = _item("Title")
    out = _format_raw(item)
    assert "YAHOO" in out
    assert "Title" in out
    assert item.url in out


def test_format_analysis_renders_sentiment_arrow_and_pairs():
    item = _item("Title")
    bear = _format_analysis(item, _result(0.9, sentiment=-0.7))
    assert "↓" in bear
    assert "EURUSD" in bear
    assert "-0.70" in bear

    bull = _format_analysis(item, _result(0.9, sentiment=0.7))
    assert "↑" in bull


def test_options_from_env_parses_csv_and_defaults(monkeypatch):
    monkeypatch.setenv("TELEGRAM_RAW_CHAT_ID", "1")
    monkeypatch.setenv("TELEGRAM_ANALYSIS_CHAT_ID", "2")
    monkeypatch.setenv("NEWS_YAHOO_TICKERS", "AAPL, MSFT ,  TSLA")
    monkeypatch.setenv("NEWS_ANALYSIS_MIN_CONFIDENCE", "0.75")
    opts = NewsServiceOptions.from_env()
    assert opts.yahoo_tickers == ("AAPL", "MSFT", "TSLA")
    assert opts.raw_chat_id == "1"
    assert opts.analysis_chat_id == "2"
    assert opts.analysis_confidence_threshold == 0.75
