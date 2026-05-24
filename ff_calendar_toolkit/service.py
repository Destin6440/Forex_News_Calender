from .console import AppConsole
from .feeds import build_context as build_feed_context, fetch_weeks
from .models import RunOptions
from .normalize import normalize_rows
from .storage import FileOutputStore

FEED_WEEK_KEYS = {"last", "this", "next"}


class ScrapeService:
    def __init__(self, console: AppConsole | None = None) -> None:
        self.console = console or AppConsole()

    def run(self, options: RunOptions) -> int:
        feed_weeks = [m.lower() for m in options.months if m.lower() in FEED_WEEK_KEYS]
        legacy_months = [m for m in options.months if m.lower() not in FEED_WEEK_KEYS]

        store = FileOutputStore(options.output_dir)
        store.begin_run(options.output_format)
        total_records = 0

        if feed_weeks:
            label = "+".join(feed_weeks)
            self.console.step(f"Fetching XML feed for weeks: {label}")

            def _warn(week, exc):
                self.console.step(f"Feed for '{week}' unavailable ({exc}); continuing")

            raw_rows = fetch_weeks(feed_weeks, on_error=_warn)
            context = build_feed_context(label, options.target_timezone)
            total_records += self._process(raw_rows, context, options, store)

        if not legacy_months:
            self.console.success(
                f"Run finished with {total_records} rows across feed weeks: "
                f"{', '.join(feed_weeks) or 'none'}"
            )
            return 0

        from .scraper import ForexFactoryScraper

        scraper = ForexFactoryScraper(
            self.console,
            headless=options.headless,
            enrich_filter_currencies=options.allowed_currencies,
            enrich_filter_impacts=options.allowed_impacts,
        )

        for month in legacy_months:
            self.console.step(f"Scraping month selector '{month}' via Selenium (legacy path)")
            raw_rows, context = scraper.scrape_month(month, options.target_timezone)
            total_records += self._process(raw_rows, context, options, store)

        self.console.success(f"Run finished with {total_records} rows across {len(options.months)} month(s)")
        return 0

    def _process(self, raw_rows, context, options: RunOptions, store: FileOutputStore) -> int:
        self.console.step(
            f"Normalizing {len(raw_rows)} raw rows for {context.month_name} {context.year}"
        )
        records = normalize_rows(
            raw_rows,
            context.year,
            context.source_timezone,
            options.target_timezone,
            options.allowed_currencies,
            options.allowed_impacts,
            context.scraped_at,
        )
        self.console.step(
            f"Writing {len(records)} filtered rows as {options.output_format} output"
        )
        result = store.write(records, context, options.output_format)
        self.console.success(
            f"{context.month_name} {context.year}: {len(records)} rows written to {options.output_dir}"
        )
        self.console.step(
            f"Last-run artifacts: {', '.join(str(path) for path in result.last_run_paths)}"
        )
        return len(records)
