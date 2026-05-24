"""Shared HTTP helper for news/calendar sources.

Replaces ad-hoc `urllib.request` calls with a `requests.Session` that handles:
- urllib3 retry with exponential backoff (honoring Retry-After when sent)
- connection pooling (cheap reuse across same-host fetches)
- a truthful but plausible browser UA (Yahoo blocks generic Python UAs)

Source-specific quirks NOT handled here:
- GDELT enforces 5s/req with a plain-text 200 body — call sites must pace
  manually (urllib3 can't see this because it's not an HTTP error code).
- Yahoo's RSS endpoint can issue multi-hour IP blocks if hit too frequently;
  upstream cron interval must be >=5 min for the default 5-ticker fan-out.
"""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_DEFAULT_TIMEOUT = 30


def build_session(
    max_retries: int = 3,
    backoff_factor: float = 1.5,
    pool_size: int = 4,
) -> requests.Session:
    """Build a requests.Session with retry + pooling configured for news fetches.

    Retry triggers on 429/5xx; backoff is `backoff_factor * (2 ** retry)`, so
    1.5 → 0s, 3s, 6s, 12s. Yahoo's 429 doesn't include Retry-After, so the
    backoff_factor matters. Cap retries at 3 for Yahoo specifically to avoid
    deepening blocks; call sites can lower this per request via a fresh
    session.
    """
    retry = Retry(
        total=max_retries,
        connect=max_retries,
        read=max_retries,
        status=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=pool_size,
        pool_maxsize=pool_size,
    )
    session = requests.Session()
    session.headers.update({
        "User-Agent": _USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
    })
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def http_get(
    url: str,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    accept: str = "*/*",
    session: requests.Session | None = None,
) -> bytes:
    """Fetch URL and return raw bytes. Raises on non-2xx after retries.

    Pass a shared session for multiple calls to amortize connection setup.
    Without one, a one-shot session is built per call — fine for low volume.
    """
    own_session = session is None
    sess = session or build_session()
    try:
        resp = sess.get(url, headers={"Accept": accept}, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    finally:
        if own_session:
            sess.close()
