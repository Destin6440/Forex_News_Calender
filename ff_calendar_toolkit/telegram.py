"""Telegram sender with per-chat rate limiting.

Telegram limits: ~30 msg/sec globally and ~1 msg/sec per chat. We enforce the per-chat
limit with a token bucket per chat_id. The global cap is generous enough that single-
chat pacing covers it in practice for this pipeline.

Two channels are typical: TELEGRAM_RAW_CHAT_ID for unfiltered headlines, and
TELEGRAM_ANALYSIS_CHAT_ID for LLM-analyzed posts.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable
from urllib import parse, request
from urllib.error import HTTPError, URLError


class TelegramError(RuntimeError):
    pass


@dataclass
class _ChatBucket:
    """1 token per chat per `interval_secs`. Simple sleep-to-acquire."""

    interval_secs: float
    next_allowed_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def acquire(self, now_fn: Callable[[], float], sleep_fn: Callable[[float], None]) -> None:
        with self.lock:
            now = now_fn()
            wait = self.next_allowed_at - now
            if wait > 0:
                sleep_fn(wait)
                now = now_fn()
            self.next_allowed_at = now + self.interval_secs


class TelegramSender:
    def __init__(
        self,
        bot_token: str,
        per_chat_interval_secs: float = 1.0,
        timeout_secs: int = 10,
        now_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
        http_post: Callable[[str, bytes], None] | None = None,
    ) -> None:
        if not bot_token:
            raise TelegramError("bot_token is required")
        self.bot_token = bot_token
        self.per_chat_interval_secs = per_chat_interval_secs
        self.timeout_secs = timeout_secs
        self._now = now_fn
        self._sleep = sleep_fn
        self._http_post = http_post or self._default_post
        self._buckets: dict[str, _ChatBucket] = {}
        self._buckets_lock = threading.Lock()

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "TelegramSender":
        env = env if env is not None else os.environ
        token = env.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
        interval = float(env.get("TELEGRAM_PER_CHAT_INTERVAL_SECS", "1.0"))
        return cls(bot_token=token, per_chat_interval_secs=interval)

    def _bucket_for(self, chat_id: str) -> _ChatBucket:
        with self._buckets_lock:
            bucket = self._buckets.get(chat_id)
            if bucket is None:
                bucket = _ChatBucket(interval_secs=self.per_chat_interval_secs)
                self._buckets[chat_id] = bucket
            return bucket

    def send(self, chat_id: str, text: str, parse_mode: str | None = None) -> None:
        if not chat_id:
            raise TelegramError("chat_id is required")
        self._bucket_for(chat_id).acquire(self._now, self._sleep)
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        body = {"chat_id": chat_id, "text": text}
        if parse_mode:
            body["parse_mode"] = parse_mode
        self._http_post(url, parse.urlencode(body).encode("utf-8"))

    def _default_post(self, url: str, payload: bytes) -> None:
        req = request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_secs) as resp:
                if getattr(resp, "status", 200) >= 400:
                    raise TelegramError(f"HTTP {resp.status} from Telegram")
        except HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = "<unreadable>"
            try:
                err_payload = json.loads(body)
                description = err_payload.get("description", body[:200])
            except json.JSONDecodeError:
                description = body[:200]
            raise TelegramError(f"HTTP {exc.code} from Telegram: {description}") from exc
        except URLError as exc:
            raise TelegramError(f"Telegram connection error: {exc.reason}") from exc
