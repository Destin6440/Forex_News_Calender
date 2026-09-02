# Forex Factory Calendar Database

A local-first, repeatable calendar ingestion toolkit based on **fizahkhalid/forex_factory_calendar_news_scraper**. It builds a canonical SQLite database for research and backtesting; it does not execute trades. The original MIT license and attribution are preserved in [`LICENSE`](LICENSE).

## Coverage and provenance

The bootstrap source is the MIT-licensed [Ehsanrs2 Forex Factory Calendar dataset](https://huggingface.co/datasets/Ehsanrs2/Forex_Factory_Calendar), documented by its publisher as covering **2007-01-01 through 2025-04-07**. Later gaps are read from ordinary monthly Forex Factory pages with Selenium, and current/revised events from Forex Factory's [public weekly JSON export](https://nfs.faireconomy.media/ff_calendar_thisweek.json). The toolkit retains every currency and red, orange, yellow, and gray event. Filtering is query-time only.

Source availability controls achievable coverage. Forex Factory or Hugging Face may rate-limit, change markup, or show a security challenge. The program never bypasses those controls: the affected month remains incomplete, `sync_state.json` is not advanced, and the command fails clearly. Never interpret the advertised archive range as proof that your local database is complete—`validate --strict` and `data/dataset_manifest.json` are authoritative.

## Clean installation

Python 3.11+ and Chrome/Chromium with a compatible driver are recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m ff_calendar_toolkit.cli sync
python -m ff_calendar_toolkit.cli validate --strict
```

On Windows PowerShell, replace activation with:

```powershell
.venv\Scripts\Activate.ps1
```

Generated databases, manifests, state, and exports live under `data/` and are intentionally ignored by Git.

## Commands

```bash
# Download and import the archive (or use --archive-file legitimate.csv)
python -m ff_calendar_toolkit.cli bootstrap

# Fetch ordinary monthly pages; "today" is accepted for --end
python -m ff_calendar_toolkit.cli backfill --start 2025-04-08 --end today

# Upsert current/revised events from the public weekly export
python -m ff_calendar_toolkit.cli update

# One repeatable command: bootstrap, gaps/recent/upcoming, update, validation, exports
python -m ff_calendar_toolkit.cli sync

python -m ff_calendar_toolkit.cli validate --strict
python -m ff_calendar_toolkit.cli export --format csv parquet
```

### Saved-HTML recovery

If an ordinary request displays CAPTCHA, Cloudflare, or another verification page, stop. Using a normal browser, legitimately open the calendar month and save the rendered calendar page. Then import it without bypassing the control:

```bash
python -m ff_calendar_toolkit.cli import-html saved_calendar.html --period 2025-05
# Or put files such as 2025-05.html in a directory:
python -m ff_calendar_toolkit.cli backfill --start 2025-05-01 --end 2025-05-31 --html-directory saved-pages
```

Verification pages, malformed HTML, and empty calendars are rejected. Failed months remain `incomplete` and are retried; rerun `sync` after supplying legitimate input or after source access recovers.

### Ordinary-Chrome handoff (recommended)

For a full unattended month sequence after one legitimate manual page load, use:

```bash
python -m ff_calendar_toolkit.cli sync --browser-handoff
```

The toolkit launches an ordinary visible Chrome process with a dedicated local
profile and opens the first missing month before Selenium is connected. Wait
until real calendar rows are visible, complete any verification manually if it
appears, then return to Terminal and press Enter. Only then does the toolkit
attach to that already-open browser and continue through every remaining month
using the same session. It waits five seconds between months by default. If a
verification page reappears, the importer pauses and returns control to you; it
never clicks, solves, hides, or bypasses the challenge.

The handoff profile is stored under `data/chrome-handoff-profile` and is ignored
by Git. `--browser-handoff` and `--interactive-browser` are mutually exclusive.
The handoff mode is also available for bounded backfills:

```bash
python -m ff_calendar_toolkit.cli backfill \
  --start 2025-04-01 --end today --browser-handoff
```

The archive ends on 2025-04-07, so April 2025 is intentionally treated as a
partial month and retrieved again. Existing databases that previously marked
that month complete are repaired automatically during the next sync.

### Selenium interactive-browser recovery (legacy)

The older Selenium-created recovery mode remains available:

```bash
python -m ff_calendar_toolkit.cli sync --interactive-browser
```

This opens one visible Chrome window and reuses it for every requested month. If
a verification page appears, complete it manually in Chrome; the toolkit never
solves or bypasses the control. It keeps the window open for up to 10 minutes and
continues only after recognizable calendar rows appear. Legitimately issued
cookies and browser state are retained locally in `data/chrome-profile` for later
runs (the directory is ignored by Git). Headless browsing remains the default.

The same mode is available for a bounded recovery, for example:

```bash
python -m ff_calendar_toolkit.cli backfill --start 2025-05-01 --end 2025-05-31 --interactive-browser
```

## Canonical data and identity

`data/forex_factory.sqlite` is canonical. The `events` table includes:

- identity: `event_key`, `source_event_id`
- event: `event_name`, `event_name_normalized`, `currency`, `impact_color`, `impact_level`
- schedule: `date_et`, `time_et`, `datetime_et`, `datetime_utc`, `all_day`
- release values: `actual`, `forecast`, `previous`
- provenance: `source_url`, `source_type`, `source_period`, `raw_impact`, `raw_date`, `raw_time`
- audit times: `first_seen_at`, `last_seen_at`, `scraped_at`

Times use the IANA `America/New_York` zone and are converted to UTC using real daylight-saving rules. An upstream event ID is preferred. Otherwise, a SHA-256 key is deterministically derived from Eastern date, Eastern time/all-day, currency, and normalized name. Upserts preserve `first_seen_at` and revise mutable fields. The `periods` table records complete/incomplete month attempts.

Exports are stable-sorted and complete:

- `data/exports/forex_factory_calendar_full.csv`
- `data/exports/forex_factory_calendar_full.parquet`

## Incremental behavior and validation

A successful sync re-reads at least the preceding 60 days, includes the current and following month, retries missing/incomplete months, applies weekly revisions, exports, validates, and only then atomically writes `data/sync_state.json`. `data/dataset_manifest.json` reports exact local bounds and counts, missing/incomplete months, duplicates, required-field/date issues, provenance, last successful sync, and export SHA-256 hashes.

Strict validation exits nonzero for duplicate keys, historical month gaps, invalid impacts/dates, incomplete or suspiciously empty months, and missing essential fields:

```bash
python -m ff_calendar_toolkit.cli validate --strict
```

## Configuration search

```bash
python -m ff_calendar_toolkit.cli find-configuration \
  --event "ADP Non-Farm Employment Change" \
  --currencies USD EUR \
  --counted-impacts red orange \
  --only
```

`--only` requires the event and rejects a date containing another selected-currency red/orange event. Stored yellow/gray events are shown as ignored and do not disqualify it. Each result includes the date, matching event, all counted events, ignored events, and an explanation. With a complete validated archive, 2023-08-02 and 2023-12-06 are regression matches while 2024-05-01 fails due to other counted events; these outcomes are computed from data, never hard-coded.

## Testing

Normal tests use local strings/fixtures and do not need live access:

```bash
python -m pytest -q
```

Live source checks are operational commands rather than mandatory unit tests because rate limits and security pages are external conditions.

## Limitations

Forex Factory does not promise a permanent public historical API or stable HTML. Upstream corrections can change old records. Events without upstream IDs use schedule/name identity, so a simultaneous change of both name and schedule can appear as a new logical event. Parquet export requires `pyarrow`. All source data remains subject to its source terms; toolkit code remains MIT licensed.
