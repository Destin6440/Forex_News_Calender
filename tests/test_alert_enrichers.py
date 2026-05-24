import json
import os
import unittest
from datetime import datetime
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

import pytz

from ff_calendar_toolkit.alerts.enrichers import (
    EnrichmentError,
    MathSentimentEnricher,
    OpenAIEnricher,
    _to_float,
)
from ff_calendar_toolkit.alerts.models import AlertEvent


class _SilentConsole:
    def step(self, *_a, **_k): pass
    def success(self, *_a, **_k): pass
    def warn(self, *_a, **_k): pass
    def error(self, *_a, **_k): pass


def _make_event(payload_overrides=None):
    base = {
        "event": "Core CPI m/m",
        "currency": "USD",
        "impact": "red",
        "actual": "3.1",
        "forecast": "2.8",
        "previous": "2.9",
    }
    if payload_overrides:
        base.update(payload_overrides)
    return AlertEvent(
        event_id="event-1",
        event_time=pytz.timezone("UTC").localize(datetime(2026, 4, 1, 12, 30)),
        payload=base,
    )


class ToFloatTests(unittest.TestCase):
    def test_parses_plain_number(self):
        self.assertEqual(_to_float("3.1"), 3.1)

    def test_parses_negative(self):
        self.assertEqual(_to_float("-0.4"), -0.4)

    def test_parses_percent(self):
        self.assertEqual(_to_float("2.5%"), 2.5)

    def test_parses_thousands_suffix(self):
        self.assertEqual(_to_float("250K"), 250_000)

    def test_parses_commas(self):
        self.assertEqual(_to_float("1,234.5"), 1234.5)

    def test_returns_none_for_dash(self):
        self.assertIsNone(_to_float("—"))
        self.assertIsNone(_to_float("-"))
        self.assertIsNone(_to_float("empty"))

    def test_returns_none_for_garbage(self):
        self.assertIsNone(_to_float("n/a"))
        self.assertIsNone(_to_float(None))


class MathSentimentEnricherTests(unittest.TestCase):
    def setUp(self):
        self.enricher = MathSentimentEnricher()

    def test_beat_when_actual_above_forecast(self):
        enriched = self.enricher.enrich(_make_event())
        self.assertIn("Beat", enriched.payload["math_sentiment"])
        self.assertIn("3.1", enriched.payload["math_sentiment"])
        self.assertIn("2.8", enriched.payload["math_sentiment"])

    def test_miss_when_actual_below_forecast(self):
        enriched = self.enricher.enrich(_make_event({"actual": "2.5", "forecast": "2.8"}))
        self.assertIn("Miss", enriched.payload["math_sentiment"])

    def test_in_line_when_equal(self):
        enriched = self.enricher.enrich(_make_event({"actual": "2.8", "forecast": "2.8"}))
        self.assertIn("In-line", enriched.payload["math_sentiment"])

    def test_skips_when_actual_missing(self):
        event = _make_event({"actual": "—"})
        enriched = self.enricher.enrich(event)
        self.assertNotIn("math_sentiment", enriched.payload)

    def test_skips_when_forecast_missing(self):
        event = _make_event({"forecast": "empty"})
        enriched = self.enricher.enrich(event)
        self.assertNotIn("math_sentiment", enriched.payload)

    def test_preserves_other_payload_keys(self):
        enriched = self.enricher.enrich(_make_event())
        self.assertEqual(enriched.payload["event"], "Core CPI m/m")
        self.assertEqual(enriched.event_id, "event-1")


class OpenAIEnricherTests(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in ("OPENAI_API_KEY", "OPENAI_MODEL")}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_disabled_when_no_api_key(self):
        enricher = OpenAIEnricher(_SilentConsole())
        event = _make_event()
        self.assertFalse(enricher.enabled)
        self.assertIs(enricher.enrich(event), event)

    def test_enriches_when_model_returns_text(self):
        os.environ["OPENAI_API_KEY"] = "sk-test"
        enricher = OpenAIEnricher(_SilentConsole())
        with patch.object(enricher, "_ask", return_value="bullish USD: hot CPI lifts rate expectations"):
            enriched = enricher.enrich(_make_event())
        self.assertEqual(
            enriched.payload["llm_sentiment"],
            "bullish USD: hot CPI lifts rate expectations",
        )

    def test_swallows_api_errors(self):
        os.environ["OPENAI_API_KEY"] = "sk-test"
        enricher = OpenAIEnricher(_SilentConsole())
        event = _make_event()
        with patch.object(enricher, "_ask", side_effect=EnrichmentError("HTTP 429")):
            self.assertIs(enricher.enrich(event), event)

    def test_cache_avoids_duplicate_calls(self):
        os.environ["OPENAI_API_KEY"] = "sk-test"
        enricher = OpenAIEnricher(_SilentConsole())
        with patch.object(enricher, "_ask", return_value="bullish USD") as fake_ask:
            enricher.enrich(_make_event())
            enricher.enrich(_make_event())
        self.assertEqual(fake_ask.call_count, 1)

    def test_cache_keyed_on_actual_values(self):
        os.environ["OPENAI_API_KEY"] = "sk-test"
        enricher = OpenAIEnricher(_SilentConsole())
        with patch.object(enricher, "_ask", return_value="bullish USD") as fake_ask:
            enricher.enrich(_make_event({"actual": "3.1"}))
            enricher.enrich(_make_event({"actual": "3.5"}))
        self.assertEqual(fake_ask.call_count, 2)

    def test_ask_posts_to_openai(self):
        os.environ["OPENAI_API_KEY"] = "sk-test"
        os.environ["OPENAI_MODEL"] = "gpt-5-nano"
        enricher = OpenAIEnricher(_SilentConsole())
        response_body = json.dumps(
            {"choices": [{"message": {"content": "bullish USD: rates higher"}}]}
        ).encode("utf-8")

        class _FakeResponse:
            def __init__(self): self._body = response_body
            def read(self): return self._body
            def __enter__(self): return self
            def __exit__(self, *args): return False

        with patch(
            "ff_calendar_toolkit.alerts.enrichers.request.urlopen",
            return_value=_FakeResponse(),
        ) as fake_urlopen:
            result = enricher._ask(_make_event().payload)
        self.assertEqual(result, "bullish USD: rates higher")
        sent_req = fake_urlopen.call_args.args[0]
        self.assertEqual(sent_req.full_url, "https://api.openai.com/v1/chat/completions")
        self.assertIn("Authorization", sent_req.headers)
        self.assertTrue(sent_req.headers["Authorization"].startswith("Bearer "))

    def test_ask_raises_on_http_error(self):
        os.environ["OPENAI_API_KEY"] = "sk-test"
        enricher = OpenAIEnricher(_SilentConsole())
        err = HTTPError(
            url="https://api.openai.com/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=BytesIO(b'{"error":"rate limited"}'),
        )
        with patch(
            "ff_calendar_toolkit.alerts.enrichers.request.urlopen",
            side_effect=err,
        ):
            with self.assertRaises(EnrichmentError):
                enricher._ask(_make_event().payload)


if __name__ == "__main__":
    unittest.main()
