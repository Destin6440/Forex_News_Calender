"""Orchestrate: fetch news from all sources → dedup → Telegram (raw + analyzed).

Designed for cron use: `python -m ff_calendar_toolkit news-check` every N minutes.

Flow:
1. Fan-in fetch (Yahoo per-ticker RSS, Bloomberg via GDELT+GNews).
2. Filter out already-seen titles via SQLite SeenStore (cross-source dedup).
3. For each new item: post raw to TELEGRAM_RAW_CHAT_ID immediately.
4. In a background thread per item: run LLM analyzer; if `confidence >= threshold`,
   post the formatted analysis to TELEGRAM_ANALYSIS_CHAT_ID.

Raw posting never blocks on the LLM. A failed analysis doesn't suppress the raw post.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .analyzer import AnalysisResult, AnalyzerConfig, AnalyzerError, analyze
from .console import AppConsole
from .dedup import SeenStore
from .models import NewsItem
from .sources import bloomberg, yahoo
from .telegram import TelegramError, TelegramSender


@dataclass(frozen=True)
class NewsServiceOptions:
    yahoo_tickers: tuple[str, ...]
    bloomberg_keywords: tuple[str, ...]
    raw_chat_id: str
    analysis_chat_id: str
    dedup_db_path: Path
    dedup_ttl_days: int = 7
    analysis_confidence_threshold: float = 0.6
    enable_analysis: bool = True
    analysis_workers: int = 4

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "NewsServiceOptions":
        env = env if env is not None else os.environ
        return cls(
            yahoo_tickers=_split_csv(env.get("NEWS_YAHOO_TICKERS", "GLD,GC=F,DXY,USDJPY=X,EURUSD=X")),
            bloomberg_keywords=_split_csv(
                env.get("NEWS_BLOOMBERG_KEYWORDS", "forex,fed,ecb,gold,inflation")
            ),
            raw_chat_id=env.get("TELEGRAM_RAW_CHAT_ID", ""),
            analysis_chat_id=env.get("TELEGRAM_ANALYSIS_CHAT_ID", ""),
            dedup_db_path=Path(env.get("NEWS_DEDUP_DB", "state/dedup/seen.db")),
            dedup_ttl_days=int(env.get("NEWS_DEDUP_TTL_DAYS", "7")),
            analysis_confidence_threshold=float(env.get("NEWS_ANALYSIS_MIN_CONFIDENCE", "0.6")),
            enable_analysis=env.get("NEWS_ANALYSIS_ENABLED", "true").lower() == "true",
            analysis_workers=int(env.get("NEWS_ANALYSIS_WORKERS", "4")),
        )


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


@dataclass
class NewsServiceStats:
    fetched: int = 0
    new_after_dedup: int = 0
    raw_posted: int = 0
    raw_failed: int = 0
    analyzed_posted: int = 0
    analysis_failed: int = 0
    analysis_below_threshold: int = 0
    errors: list[str] = field(default_factory=list)


class NewsService:
    def __init__(
        self,
        options: NewsServiceOptions,
        telegram: TelegramSender,
        seen: SeenStore,
        console: AppConsole | None = None,
        analyzer_config: AnalyzerConfig | None = None,
        analyze_fn: Callable[[NewsItem, AnalyzerConfig], AnalysisResult] = analyze,
        fetch_yahoo: Callable[..., list[NewsItem]] = yahoo.fetch_rss,
        fetch_bloomberg: Callable[..., list[NewsItem]] = bloomberg.fetch_all,
    ) -> None:
        self.options = options
        self.telegram = telegram
        self.seen = seen
        self.console = console or AppConsole()
        self.analyzer_config = analyzer_config
        self._analyze = analyze_fn
        self._fetch_yahoo = fetch_yahoo
        self._fetch_bloomberg = fetch_bloomberg

    def run(self) -> NewsServiceStats:
        stats = NewsServiceStats()
        items = self._fetch_all(stats)
        stats.fetched = len(items)
        self.console.step(f"Fetched {stats.fetched} items across sources")

        new_items = [item for item in items if self.seen.check_and_mark(item.source, item.title)]
        stats.new_after_dedup = len(new_items)
        self.console.step(f"{stats.new_after_dedup} new after dedup")

        if not new_items:
            return stats

        # Raw fanout — sequential per chat is fine (token bucket paces inside TelegramSender)
        for item in new_items:
            try:
                self.telegram.send(self.options.raw_chat_id, _format_raw(item))
                stats.raw_posted += 1
            except TelegramError as exc:
                stats.raw_failed += 1
                stats.errors.append(f"raw-send '{item.title[:40]}': {exc}")
                self.console.error(f"raw-send failed: {exc}")

        # Analysis fanout — only if enabled and an analysis chat is configured
        if not self.options.enable_analysis or not self.options.analysis_chat_id:
            return stats

        with ThreadPoolExecutor(max_workers=self.options.analysis_workers) as pool:
            list(pool.map(lambda it: self._analyze_and_post(it, stats), new_items))

        return stats

    def _fetch_all(self, stats: NewsServiceStats) -> list[NewsItem]:
        def _on_err(source_label: str):
            def _cb(detail, exc):
                stats.errors.append(f"{source_label}[{detail}]: {exc}")
                self.console.error(f"{source_label} fetch error for {detail}: {exc}")

            return _cb

        items: list[NewsItem] = []
        if self.options.yahoo_tickers:
            items.extend(self._fetch_yahoo(self.options.yahoo_tickers, on_error=_on_err("yahoo")))
        if self.options.bloomberg_keywords:
            items.extend(
                self._fetch_bloomberg(keywords=self.options.bloomberg_keywords, on_error=_on_err("bloomberg"))
            )
        return items

    def _analyze_and_post(self, item: NewsItem, stats: NewsServiceStats) -> None:
        try:
            result = self._analyze(item, self.analyzer_config) if self.analyzer_config else self._analyze(item)
        except AnalyzerError as exc:
            stats.analysis_failed += 1
            stats.errors.append(f"analyze '{item.title[:40]}': {exc}")
            self.console.error(f"analyze failed: {exc}")
            return

        if result.confidence < self.options.analysis_confidence_threshold:
            stats.analysis_below_threshold += 1
            return

        try:
            self.telegram.send(self.options.analysis_chat_id, _format_analysis(item, result))
            stats.analyzed_posted += 1
        except TelegramError as exc:
            stats.analysis_failed += 1
            stats.errors.append(f"analyzed-send '{item.title[:40]}': {exc}")
            self.console.error(f"analyzed-send failed: {exc}")


def _format_raw(item: NewsItem) -> str:
    parts = [
        f"[{item.source.upper()}] {item.title}",
        item.url,
    ]
    if item.tickers:
        parts.append(f"Tickers: {', '.join(item.tickers)}")
    return "\n".join(parts)


def _format_analysis(item: NewsItem, result: AnalysisResult) -> str:
    arrow = "↑" if result.sentiment > 0 else ("↓" if result.sentiment < 0 else "→")
    pairs = ", ".join(result.affected_pairs) if result.affected_pairs else "—"
    return (
        f"[{item.source.upper()} • {result.time_horizon}]\n"
        f"{arrow} sentiment={result.sentiment:+.2f}  confidence={result.confidence:.2f}\n"
        f"pairs: {pairs}\n"
        f"{result.summary}\n"
        f"— {item.title}\n"
        f"{item.url}"
    )
