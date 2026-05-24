import json

import pytest

from ff_calendar_toolkit import analyzer
from ff_calendar_toolkit.analyzer import (
    AnalysisResult,
    AnalyzerConfig,
    AnalyzerError,
    _extract_json,
    _validate_horizon,
    analyze,
)
from ff_calendar_toolkit.models import NewsItem


ITEM = NewsItem(
    source="yahoo",
    title="Fed signals pause; dollar slides",
    url="https://x/y",
    published_at="2026-05-23T20:00:00+00:00",
    summary="Powell hints at hold.",
    tickers=("DXY",),
)

GOOD_PAYLOAD = {
    "sentiment": -0.6,
    "affected_pairs": ["EURUSD", "xauusd"],
    "time_horizon": "short",
    "confidence": 0.75,
    "summary": "Dovish Fed → USD bearish near-term.",
}


def _wrap(content_obj: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(content_obj)}}]}


def test_validate_horizon_falls_back_for_garbage():
    assert _validate_horizon("short") == "short"
    assert _validate_horizon("MEDIUM ") == "medium"
    assert _validate_horizon("nonsense") == "short"


def test_extract_json_strips_code_fences():
    payload = _extract_json('```json\n{"a": 1}\n```')
    assert payload == {"a": 1}


def test_extract_json_finds_object_in_prose():
    payload = _extract_json('Here is the answer: {"a": 2}. Hope it helps.')
    assert payload == {"a": 2}


def test_extract_json_raises_on_no_object():
    with pytest.raises(AnalyzerError):
        _extract_json("no json here")


def test_analysis_result_clamps_and_uppercases():
    result = AnalysisResult.from_payload({**GOOD_PAYLOAD, "sentiment": -2.0, "confidence": 1.5})
    assert result.sentiment == -1.0
    assert result.confidence == 1.0
    assert result.affected_pairs == ("EURUSD", "XAUUSD")


def test_analysis_result_rejects_bad_shape():
    with pytest.raises(AnalyzerError):
        AnalysisResult.from_payload({"sentiment": "high"})
    with pytest.raises(AnalyzerError):
        AnalysisResult.from_payload({"sentiment": 0.1, "affected_pairs": "EURUSD"})


def test_analyze_happy_path(monkeypatch):
    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured.update({"url": url, "payload": payload, "headers": headers})
        return _wrap(GOOD_PAYLOAD)

    monkeypatch.setattr(analyzer, "_post", fake_post)
    cfg = AnalyzerConfig(api_key="k", base_url="https://x.example/v1", model="m")
    result = analyze(ITEM, cfg)

    assert result.sentiment == pytest.approx(-0.6)
    assert result.affected_pairs == ("EURUSD", "XAUUSD")
    assert captured["url"] == "https://x.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer k"
    assert captured["payload"]["model"] == "m"
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert "Fed signals pause" in captured["payload"]["messages"][1]["content"]


def test_analyze_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(analyzer.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def fake_post(url, payload, headers, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise AnalyzerError("HTTP 429 from LLM API: rate limited")
        return _wrap(GOOD_PAYLOAD)

    monkeypatch.setattr(analyzer, "_post", fake_post)
    cfg = AnalyzerConfig(api_key="k", max_retries=4)
    result = analyze(ITEM, cfg)
    assert result.sentiment == pytest.approx(-0.6)
    assert calls["n"] == 3


def test_analyze_does_not_retry_on_4xx_other_than_429(monkeypatch):
    monkeypatch.setattr(analyzer.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def fake_post(url, payload, headers, timeout):
        calls["n"] += 1
        raise AnalyzerError("HTTP 401 from LLM API: bad key")

    monkeypatch.setattr(analyzer, "_post", fake_post)
    cfg = AnalyzerConfig(api_key="k", max_retries=4)
    with pytest.raises(AnalyzerError, match="HTTP 401"):
        analyze(ITEM, cfg)
    assert calls["n"] == 1


def test_analyze_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(analyzer.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def fake_post(url, payload, headers, timeout):
        calls["n"] += 1
        raise AnalyzerError("HTTP 503 from LLM API")

    monkeypatch.setattr(analyzer, "_post", fake_post)
    cfg = AnalyzerConfig(api_key="k", max_retries=2)
    with pytest.raises(AnalyzerError):
        analyze(ITEM, cfg)
    assert calls["n"] == 2


def test_config_from_env_requires_api_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(AnalyzerError):
        AnalyzerConfig.from_env()


def test_config_from_env_reads_overrides(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "abc")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "llama3.3:70b")
    monkeypatch.setenv("LLM_TIMEOUT_SECS", "12")
    cfg = AnalyzerConfig.from_env()
    assert cfg.api_key == "abc"
    assert cfg.base_url == "http://localhost:11434/v1"
    assert cfg.model == "llama3.3:70b"
    assert cfg.timeout_secs == 12
