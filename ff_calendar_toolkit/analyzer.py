"""LLM-based news analyzer.

Takes a NewsItem, returns a structured JSON signal suitable for the analysis Telegram
channel. Backend = any OpenAI-compatible Chat Completions endpoint:

- OpenRouter (default; routes to Claude, GPT, Hermes, DeepSeek, etc. via one key)
- Local vLLM / Ollama (set LLM_BASE_URL=http://localhost:11434/v1)
- Anthropic / OpenAI direct via their OpenAI-compat shims

Configuration:
  LLM_API_KEY        — required
  LLM_BASE_URL       — default https://openrouter.ai/api/v1
  LLM_MODEL          — default anthropic/claude-haiku-4.5
  LLM_TIMEOUT_SECS   — default 30
  LLM_MAX_RETRIES    — default 3

Output schema (strict JSON):
  {
    "sentiment":       float in [-1, 1],
    "affected_pairs":  list[str]  (e.g. ["XAUUSD","EURUSD"]),
    "time_horizon":    "short" | "medium" | "long",
    "confidence":      float in [0, 1],
    "summary":         str (<=200 chars)
  }
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib import parse, request
from urllib.error import HTTPError, URLError

from .models import NewsItem

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-haiku-4.5"
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3

SYSTEM_PROMPT = (
    "You are a forex/macro news analyst. Given a single news item, return ONLY a JSON "
    "object — no prose, no markdown — with this exact schema:\n"
    '{"sentiment": <float in [-1,1]>, '
    '"affected_pairs": [<string>, ...], '
    '"time_horizon": "short"|"medium"|"long", '
    '"confidence": <float in [0,1]>, '
    '"summary": <string, <=200 chars>}\n'
    "sentiment: negative means USD-bearish / risk-off; positive means USD-bullish / "
    "risk-on (or pair-bullish if pair-specific). affected_pairs: ISO 6-letter pair codes "
    "(e.g. EURUSD, XAUUSD, USDJPY). time_horizon: short=hours, medium=days, long=weeks. "
    "confidence: how confident you are the signal will move price. summary: one sentence."
)


class AnalyzerError(RuntimeError):
    pass


@dataclass(frozen=True)
class AnalyzerConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_secs: int = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES

    @classmethod
    def from_env(cls) -> "AnalyzerConfig":
        api_key = os.getenv("LLM_API_KEY", "")
        if not api_key:
            raise AnalyzerError("LLM_API_KEY is not set")
        return cls(
            api_key=api_key,
            base_url=os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL),
            model=os.getenv("LLM_MODEL", DEFAULT_MODEL),
            timeout_secs=int(os.getenv("LLM_TIMEOUT_SECS", DEFAULT_TIMEOUT)),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", DEFAULT_MAX_RETRIES)),
        )


@dataclass(frozen=True)
class AnalysisResult:
    sentiment: float
    affected_pairs: tuple[str, ...]
    time_horizon: str
    confidence: float
    summary: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AnalysisResult":
        pairs = payload.get("affected_pairs") or []
        if not isinstance(pairs, list):
            raise AnalyzerError(f"affected_pairs must be a list, got {type(pairs).__name__}")
        try:
            return cls(
                sentiment=_clamp(float(payload["sentiment"]), -1.0, 1.0),
                affected_pairs=tuple(str(p).upper() for p in pairs),
                time_horizon=_validate_horizon(str(payload.get("time_horizon", "short"))),
                confidence=_clamp(float(payload.get("confidence", 0.0)), 0.0, 1.0),
                summary=str(payload.get("summary", "")).strip()[:200],
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise AnalyzerError(f"Malformed analyzer payload: {exc}") from exc


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _validate_horizon(value: str) -> str:
    horizon = value.strip().lower()
    if horizon not in {"short", "medium", "long"}:
        return "short"
    return horizon


def _user_prompt(item: NewsItem) -> str:
    parts = [f"Source: {item.source}", f"Title: {item.title}"]
    if item.summary:
        parts.append(f"Summary: {item.summary}")
    if item.tickers:
        parts.append(f"Tickers: {', '.join(item.tickers)}")
    if item.published_at:
        parts.append(f"Published: {item.published_at}")
    return "\n".join(parts)


def _extract_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise AnalyzerError(f"No JSON object found in LLM response: {content[:200]}")
        return json.loads(text[start : end + 1])


def _post(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = "<unreadable>"
        raise AnalyzerError(f"HTTP {exc.code} from LLM API: {err_body[:300]}") from exc
    except URLError as exc:
        raise AnalyzerError(f"LLM API connection error: {exc.reason}") from exc


def _is_retryable(exc: AnalyzerError) -> bool:
    msg = str(exc)
    return any(code in msg for code in ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "connection error"))


def analyze(item: NewsItem, config: AnalyzerConfig | None = None) -> AnalysisResult:
    cfg = config or AnalyzerConfig.from_env()
    url = f"{cfg.base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(item)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }

    last_exc: AnalyzerError | None = None
    for attempt in range(1, cfg.max_retries + 1):
        try:
            response = _post(url, payload, headers, cfg.timeout_secs)
            content = response["choices"][0]["message"]["content"]
            return AnalysisResult.from_payload(_extract_json(content))
        except AnalyzerError as exc:
            last_exc = exc
            if attempt == cfg.max_retries or not _is_retryable(exc):
                raise
            time.sleep(2 ** (attempt - 1))
        except (KeyError, IndexError, TypeError) as exc:
            raise AnalyzerError(f"Unexpected LLM response shape: {exc}") from exc
    assert last_exc is not None  # unreachable
    raise last_exc
