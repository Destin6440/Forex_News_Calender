# Research Synthesis — Fetching News from ForexFactory, Bloomberg, Yahoo

Consolidates [`result_1.md`](./result_1.md) (pragmatic/code-first) and [`result_2.md`](./result_2.md) (compliance-first/cite-heavy). Reconciled against the **actual repo** as of 2026-05-24 — several research recommendations are already obsolete because the repo found better paths.

---

## TL;DR — Best-of-both stack

| Source | Primary path (in repo today) | Why this beats both research docs |
|---|---|---|
| **FF Calendar** | `nfs.faireconomy.media/ff_calendar_*.xml` — FF-sanctioned XML feeds | R1 said `cloudscraper`; R2 said "scrape lightly". Both missed the official redistribution feeds. Zero Cloudflare exposure, no ToS conflict. |
| **FF News** | _Not implemented_ — see "Gap" below | Both R1 and R2 push HTML scraping. R2's compliance warning is right; only do it as discovery for upstream pivot. |
| **Bloomberg** | **GDELT 2.0 DOC API** + **Google News RSS** (`site:bloomberg.com`) | R1's `feeds.bloomberg.com/*` RSS is undocumented and fragile (R2 caveats this). GDELT indexes Bloomberg within ~15 min, free, legal. |
| **Yahoo Finance** | Per-ticker RSS `feeds.finance.yahoo.com/rss/2.0/headline?s=<ticker>` + `yfinance` fallback | R1 pushed `query2.finance.yahoo.com` (rate-limited harder); R2 pushed `news-sitemap-index.xml` (general news, not FX-targeted). Per-ticker RSS = FX-targeted + no auth/crumb. |
| **Cross-source dedup** | SQLite `SeenStore`, SHA-256 of normalized title (cross-source key) | R2 proposed 3-pass (URL canon → external ID → title hash + time). Repo's title-only is simpler and works because dup detection is the goal, not provenance. |

---

## Per-source reconciliation

### 1. ForexFactory

**Repo today** (`ff_calendar_toolkit/feeds.py`):
- Uses `https://nfs.faireconomy.media/ff_calendar_{last,this,next}week.xml`
- Selenium scraper still exists (`scraper.py`) for the legacy monthly-archive path
- Source TZ fixed to `US/Eastern`; trade-off documented in module docstring

**Where research was wrong / incomplete:**
- R1 recommended `cloudscraper` + BS4 against `www.forexfactory.com/calendar`. Works but unnecessary — `nfs.faireconomy.media` is FF-sanctioned mirror.
- R1 recommended `ffcal` / `forex-calendar` PyPI packages. Verify before trusting — likely stale wrappers around the same feeds.
- R2 was right about compliance: `www.forexfactory.com` ToS forbids redistribution of FEED. But R2 missed `nfs.faireconomy.media` (which is the official redistribution channel — no conflict).

**Gap — FF News (not the calendar):**
Neither research path is implemented in repo. Two viable approaches:

1. **GDELT scoping**: same trick used for Bloomberg — `domain:forexfactory.com` query. Won't surface FF forum posts but will surface any FF news pages GDELT indexes.
2. **HTML scraping** (R2's selectors): `a[href^="/news/"]` on `/news`, regex `^/news/(\d+)-(slug)$`. Use **only as discovery layer** → pivot to upstream publisher (the "From <source>" line on FF news pages tells you who wrote it).

Recommendation: skip dedicated FF news scraper. GDELT + Yahoo + Bloomberg already cover FX macro news. FF's value is the **calendar**.

### 2. Bloomberg

**Repo today** (`ff_calendar_toolkit/sources/bloomberg.py`):
- **GDELT 2.0 DOC API** (`api.gdeltproject.org/api/v2/doc/doc`) — `domain:bloomberg.com (forex OR fed OR ecb ...)` query
- **Google News RSS** (`news.google.com/rss/search`) — `site:bloomberg.com <kw>` per keyword
- Deduped by URL across both paths, then SHA-256 title hash downstream

**Why this beats both research docs:**
- R1 recommended `feeds.bloomberg.com/markets/news.rss` etc. Those endpoints **exist** but are undocumented (R2 caveats: "treat as undocumented operational endpoints"). GDELT is documented, stable, free, and indexes Bloomberg directly.
- R1 recommended reverse-engineered `bloomberg.com/lineup-next/api/stories` — fragile, requires auth tokens.
- R2 recommended licensed BLPAPI/SAPI/Data License. Not viable for a personal bot ($20K+/yr).
- R2 right that consumer-site scraping = "Are you a robot?" Akamai+PerimeterX. Repo's docstring explicitly calls this out.

**What both research docs missed:**
- **GDELT** itself. R1 didn't mention it; R2 didn't either. It's the single best free source for "Bloomberg-said-X" headlines.

**Tuning ideas (not yet implemented):**
- Add a `sourcelang:eng` filter to GDELT query — already chronologically ranked but multilingual results pollute. Fixture confirms `language` field is returned per article.
- Tone scoring: GDELT's DOC API in `ArtList` mode does **not** include tone (verified via 2026-05-24 fixture — keys are `domain`, `language`, `seendate`, `socialimage`, `sourcecountry`, `title`, `url`, `url_mobile`). Tone lives in different DOC API modes (`ArtTonality`, `ArtGraph`) — would need a second request per article or batch.
- `url_mobile` and `socialimage` available in `ArtList` response but not currently consumed by parser.

**GDELT quirks discovered during fixture capture (2026-05-24):**
- **5 sec/req rate limit** enforced globally per IP; returns plain-text error `"Please limit requests to one every 5 seconds..."` instead of HTTP 429 + `Retry-After`. Generic `urllib3.Retry(respect_retry_after_header=True)` can't catch this — needs **application-level pacing** (`time.sleep(5)` between fetches).
- **Phrase minimum**: GDELT rejects quoted tokens shorter than 4 chars with `"The specified phrase is too short."`. The repo originally shipped with defaults `("forex","currency","fed","ecb","gold")` — `"fed"` and `"ecb"` are 3 chars, so the whole quoted OR-clause was rejected. `_parse_gdelt` then saw non-JSON, raised, was swallowed by `on_error` → **silent zero**. The Google News path still emitted items, masking the failure. Fixed 2026-05-24 → defaults now `("forex","currency","dollar","euro","inflation","gold")`. Regression test `test_fetch_gdelt_default_keywords_meet_gdelt_phrase_minimum` guards against re-introduction.
- **Error responses are HTTP 200** with plain-text body — `_parse_gdelt` should detect non-JSON bodies before calling `json.loads`, or `_http_get` should sniff content-type. Currently it raises and `on_error` masks it.
- **Connection timeouts** observed from some networks — GDELT API has no SLA, treat failures as expected.

### 3. Yahoo Finance

**Repo today** (`ff_calendar_toolkit/sources/yahoo.py`):
- Per-ticker RSS: `feeds.finance.yahoo.com/rss/2.0/headline?s=<ticker>` (no auth, plain XML)
- `yfinance` fallback path (opt-in; needs `curl_cffi` for crumb bypass)
- Default tickers: `GLD,GC=F,DXY,USDJPY=X,EURUSD=X` (FX-targeted)

**Reconciliation:**
- R1 #A recommended `yfinance` — repo has it as **fallback only** (correct: harder rate limits than RSS).
- R1 #B recommended `query2.finance.yahoo.com/v1/finance/search` — viable but rate-limits more aggressively than the legacy RSS endpoint. Repo's RSS path is the better default.
- R1 #D mentioned `finance.yahoo.com/news/rssindex` — generic news, not FX-targeted. Per-ticker RSS wins for this use case.
- R2 pushed `news-sitemap-index.xml` for **general** Yahoo News. Different product (`www.yahoo.com/news/` vs `finance.yahoo.com`). Not relevant for FX.
- R2's 429 observation applies to `www.yahoo.com/news` page fetches. `feeds.finance.yahoo.com` RSS doesn't 429 the same way.

**Open question:**
- Per-ticker RSS returns ~20 items per ticker per fetch. With 5 default tickers + cross-source dedup, that's plenty. If we need more breadth (commodities, indices), add tickers — don't switch endpoints.

**Yahoo rate-limit quirk discovered during fixture capture (2026-05-24):**
- `feeds.finance.yahoo.com` enforces aggressive per-IP rate limits. Observed: ~5 requests within 5 min triggered a block that lasted **>1 hour** (block extends with each retry hit during the cool-down).
- Production implication: 5 default tickers × 1 fetch per cron run = 5 requests. **Cron interval must be ≥5 min** to avoid recurrent blocks. Currently `news-check` is called manually — if you wire a scheduler, set interval ≥5min for Yahoo or batch all tickers behind a shared longer pacing window.
- Retry-on-429 makes the block **worse**, not better. `urllib3.Retry` with `respect_retry_after_header=True` is safe (Yahoo doesn't send `Retry-After`, so urllib3 falls back to `backoff_factor`), but a tight retry loop will deepen the block. Cap retries at 2 with multi-minute backoff for Yahoo.

---

## Cross-cutting patterns

### Already in repo (good)
- **Dedup**: `SeenStore` (SQLite, SHA-256 of normalized title, 7-day TTL, cross-source). Simpler than R2's 3-pass; works because we want "have we shown this headline" not "are these the same article."
- **Fan-in fetch → dedup → Telegram raw → LLM analyze → Telegram analysis** pipeline in `news_service.py`.
- **Per-source `on_error` callback** pattern — failures in one source don't block others.
- **Raw-first**: Telegram raw post happens before LLM analyze. Analysis failure doesn't suppress headline.

### Could borrow from research

From **R2**:
- **`requests-cache` + `Retry(respect_retry_after_header=True)`** — repo uses raw `urllib.request`. Switching to `requests` + `urllib3.Retry` would handle 429 backoff automatically. Worth doing if Yahoo RSS or GDELT starts rate-limiting.
- **Truthful UA with contact** — repo uses Mozilla UA. R2's `YourCompanyNewsBot/1.0 (+ops@example.com)` pattern is more honest. Tradeoff: some endpoints (Yahoo) prefer browser UA. Keep current behavior, but document why.
- **Fixture-based parser tests** — repo doesn't have these for sources. Worth adding given GDELT/RSS schemas can drift.

From **R1**:
- **`trafilatura` for full body extraction** if you ever want body text (not just headlines). Currently the pipeline runs on title-only — LLM analyzer sees just `title`. If analyzer accuracy is limited by missing context, fetch the article URL and run `trafilatura.extract()` before passing to LLM.
- **`newspaper3k` as alternative** — older, more dependencies; prefer `trafilatura`.

### Skip (research recommended, but wrong for this repo)

- **Bloomberg BLPAPI / SAPI / Data License** (R2) — not viable for personal bot.
- **`feeds.bloomberg.com` direct RSS** (R1) — works today, undocumented, fragile. GDELT is strictly better.
- **`fake_useragent` UA rotation** (R1) — R2 right: evasion, not engineering.
- **Headless browser** (R1 #C, R2 fallback) — repo's `scraper.py` has Selenium for legacy FF monthly archive. Don't extend to news sources; the feed/API paths cover the need.
- **`query2.finance.yahoo.com`** (R1) for FX — per-ticker RSS is simpler.
- **News API / Newscatcher / GNews API** (R1) — paid, redundant with GDELT for our use case.

---

## Concrete next-step recommendations

In rough priority order (highest leverage first):

1. **Add fixture-based parser tests** for `bloomberg.py` and `yahoo.py`. Capture one real GDELT JSON response, one Google News RSS XML, one Yahoo RSS XML, commit to `tests/fixtures/`. Test parsers against fixtures so schema drift surfaces in CI, not at 3am.

2. **Migrate `_http_get` to `requests` + `urllib3.Retry`**. Single shared helper in `ff_calendar_toolkit/_http.py`. Gets `Retry-After` honoring + connection pooling for free. Touches: `feeds.py`, `sources/bloomberg.py`, `sources/yahoo.py`, `scraper.py`.

3. ~~**Add GDELT tone passthrough**~~ — invalidated 2026-05-24 fixture inspection. `ArtList` mode (what we use) returns no tone field; tone requires a second GDELT request via `ArtTonality` mode or per-article enrichment via `GKG`. Cost/complexity probably exceeds value vs. existing LLM analyzer. Consider only if LLM costs become a problem.

4. ~~**(Optional) FF news via GDELT**~~ — measured 2026-05-24, dropped. `domain:forexfactory.com` query against GDELT returns `{}` over 90 days with no keyword filter. GDELT does not index forexfactory.com (likely robots.txt exclusion or GDELT's aggregator/forum filter). Do not retry.

5. ~~**(Optional) Body extraction** with `trafilatura`~~ — measured 2026-05-24, dropped. Audit of `analyzer._user_prompt` shows GNews and Yahoo already send description text to the LLM; only the GDELT path is headline-only. GDELT's article targets are Bloomberg paywalled URLs — trafilatura would extract paywall stubs, not body text. Adds dependency + per-item fetch latency for minimal real signal. Revisit only if LLM accuracy on GDELT items becomes a measurable problem.

6. **(Skip) FF news HTML scraper**. Both research docs push it; both research docs underestimate compliance risk. GDELT + Yahoo + Bloomberg cover the macro signal.

---

## Confidence calibration

- **High confidence**: GDELT for Bloomberg, FF XML feeds for calendar, per-ticker Yahoo RSS. All implemented, all working.
- **Medium confidence**: Google News RSS for Bloomberg — Google rate-limits and rotates query syntax occasionally. Watch for empty results.
- **Low confidence (avoid)**: `feeds.bloomberg.com/*.rss`, `query2.finance.yahoo.com`, direct `bloomberg.com`/`forexfactory.com` HTML scraping. Either fragile, rate-limited, or compliance-risky.

---

## Citations

R1 cites: none (model-generated knowledge).
R2 cites: 50+ Bloomberg/Yahoo/FF official doc references — useful when defending architectural decisions in writing, but R2's recommendations don't always survive contact with "I'm a hobbyist, not an enterprise."
Repo's actual implementations: GDELT 2.0 DOC API (https://api.gdeltproject.org/api/v2/doc/doc), `nfs.faireconomy.media` FF feeds (FF-sanctioned), `feeds.finance.yahoo.com/rss/2.0/headline` (legacy Yahoo Finance endpoint, stable since ~2010).
