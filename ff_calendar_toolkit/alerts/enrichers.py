"""Alert payload enrichers.

Two enrichers compose to add a Sentiment line to outgoing alert messages:

* MathSentimentEnricher — always on; emits neutral beat/miss facts derived
  from actual/forecast/previous already present in the Forex Factory payload.
  No network, no opinion.
* OpenAIEnricher — opt-in via the OPENAI_API_KEY environment variable;
  asks the model for a one-line directional read on the event. Failures are
  swallowed so enrichment never blocks the alert pipeline.

Enrichers write their output into distinct payload keys (`math_sentiment`,
`llm_sentiment`); the notifier joins whichever keys are present.
"""

from __future__ import annotations

import json
import os
import time
from typing import Protocol
from urllib import request
from urllib.error import HTTPError, URLError

from .models import AlertEvent

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
DEFAULT_CACHE_TTL_SECONDS = 3600
REQUEST_TIMEOUT_SECONDS = 15


class EnrichmentError(RuntimeError):
    pass


class Enricher(Protocol):
    def enrich(self, event: AlertEvent) -> AlertEvent: ...


def _to_float(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"—", "-", "empty"}:
        return None
    suffix_map = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}
    multiplier = 1.0
    if text[-1].upper() in suffix_map:
        multiplier = suffix_map[text[-1].upper()]
        text = text[:-1]
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


class MathSentimentEnricher:
    def enrich(self, event: AlertEvent) -> AlertEvent:
        payload = event.payload
        actual = _to_float(payload.get("actual"))
        forecast = _to_float(payload.get("forecast"))
        if actual is None or forecast is None:
            return event
        delta = actual - forecast
        if abs(delta) < 1e-9:
            line = f"In-line: actual={payload['actual']} forecast={payload['forecast']}"
        else:
            direction = "Beat" if delta > 0 else "Miss"
            pct = (delta / forecast * 100) if forecast else None
            pct_text = f", {pct:+.1f}%" if pct is not None and abs(forecast) > 1e-9 else ""
            line = (
                f"{direction}: actual={payload['actual']} vs forecast={payload['forecast']} "
                f"({delta:+g}{pct_text})"
            )
        enriched_payload = dict(payload)
        enriched_payload["math_sentiment"] = line
        return AlertEvent(
            event_id=event.event_id,
            event_time=event.event_time,
            payload=enriched_payload,
        )


class OpenAIEnricher:
    def __init__(self, console, cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
        self.console = console
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        self.cache_ttl = cache_ttl_seconds
        self._cache: dict[str, tuple[float, str]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def enrich(self, event: AlertEvent) -> AlertEvent:
        if not self.enabled:
            return event
        payload = event.payload
        event_name = payload.get("event")
        currency = payload.get("currency")
        if not event_name or not currency:
            return event
        cache_key = "|".join(
            [
                str(currency),
                str(event_name),
                str(payload.get("actual", "")),
                str(payload.get("forecast", "")),
                str(payload.get("previous", "")),
            ]
        )
        now = time.time()
        cached = self._cache.get(cache_key)
        if cached and now - cached[0] < self.cache_ttl:
            sentiment = cached[1]
        else:
            try:
                sentiment = self._ask(payload)
            except EnrichmentError as exc:
                self.console.step(f"OpenAI enrichment skipped: {exc}")
                return event
            self._cache[cache_key] = (now, sentiment)
        if not sentiment:
            return event
        enriched_payload = dict(payload)
        enriched_payload["llm_sentiment"] = sentiment
        return AlertEvent(
            event_id=event.event_id,
            event_time=event.event_time,
            payload=enriched_payload,
        )

    def _ask(self, payload: dict) -> str:
        actual = (payload.get("actual") or "").strip()
        actual_note = actual if actual else "(not yet released)"
        prompt = (
            "You are a forex news analyst. Given this economic event, "
            "give ONE short line (max 18 words) judging the likely directional bias "
            "for the listed currency. If the actual reading is '(not yet released)', "
            "base your read on forecast vs previous only and frame it as a forward expectation. "
            "Format: '<bullish|bearish|neutral> <CCY>: <one-sentence reason>'.\n\n"
            f"Event: {payload.get('event','')}\n"
            f"Currency: {payload.get('currency','')}\n"
            f"Impact: {payload.get('impact','')}\n"
            f"Actual: {actual_note}\n"
            f"Forecast: {payload.get('forecast','')}\n"
            f"Previous: {payload.get('previous','')}"
        )
        body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": 400,
            }
        ).encode("utf-8")
        req = request.Request(
            OPENAI_ENDPOINT,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = ""
            try:
                detail = f" — {exc.read().decode('utf-8', errors='replace')[:200]}"
            except Exception:
                pass
            raise EnrichmentError(f"OpenAI HTTP {exc.code}{detail}") from exc
        except URLError as exc:
            raise EnrichmentError(f"OpenAI connection error: {exc.reason}") from exc
        try:
            data = json.loads(raw)
            text = data["choices"][0]["message"]["content"].strip()
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            raise EnrichmentError(f"OpenAI unexpected response: {exc}") from exc
        # Collapse newlines so the alert stays single-line.
        return " ".join(text.split())
