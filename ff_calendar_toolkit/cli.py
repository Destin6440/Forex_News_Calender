from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_VIEWER_HOST, DEFAULT_VIEWER_PORT = "127.0.0.1", 8501

DATA_COMMANDS = {"bootstrap", "backfill", "update", "sync", "validate", "export", "export-yearly-excel", "import-html", "find-configuration"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Professional local-first Forex Factory calendar toolkit."
    )
    subparsers = parser.add_subparsers(dest="command")

    bootstrap = subparsers.add_parser("bootstrap", help="Download/import the MIT historical archive")
    bootstrap.add_argument("--archive-file", help="Legitimate local CSV/Parquet archive fallback")
    backfill = subparsers.add_parser("backfill", help="Retrieve historical calendar months")
    backfill.add_argument("--start", required=True); backfill.add_argument("--end", required=True)
    backfill.add_argument("--html-directory", type=Path, help="Directory of YYYY-MM.html saved pages")
    backfill.add_argument("--interactive-browser", action="store_true", help="Show Chrome and wait for manual verification when required")
    backfill.add_argument("--browser-handoff", action="store_true", help="Hand an ordinary dedicated Chrome session to Selenium after Enter")
    subparsers.add_parser("update", help="Upsert the public weekly calendar")
    sync = subparsers.add_parser("sync", help="Bootstrap, backfill, update, validate and export")
    sync.add_argument("--archive-file")
    sync.add_argument("--interactive-browser", action="store_true", help="Show Chrome and wait for manual verification when required")
    sync.add_argument("--browser-handoff", action="store_true", help="Hand an ordinary dedicated Chrome session to Selenium after Enter")
    sync.add_argument("--force-refresh-start", type=_cli_date, metavar="YYYY-MM-DD", help="Re-fetch every month from this date through the current month")
    sync.add_argument("--yearly-excel-dir", type=Path, help="Generate reconciled yearly Excel workbooks after strict validation")
    validate = subparsers.add_parser("validate", help="Validate canonical database")
    validate.add_argument("--strict", action="store_true")
    export = subparsers.add_parser("export", help="Create deterministic complete exports")
    export.add_argument("--format", nargs="+", choices=["csv", "parquet"], required=True)
    yearly = subparsers.add_parser("export-yearly-excel", help="Strictly validate and atomically create yearly Excel workbooks")
    yearly.add_argument("--output-dir", type=Path, required=True)
    imported = subparsers.add_parser("import-html", help="Import a legitimately saved calendar page")
    imported.add_argument("path", type=Path); imported.add_argument("--period", help="YYYY-MM (inferred from events when omitted)")
    find = subparsers.add_parser("find-configuration", help="Find historical same-day event configurations")
    find.add_argument("--event", required=True); find.add_argument("--currencies", nargs="+", required=True)
    find.add_argument("--counted-impacts", nargs="+", required=True, choices=["red","orange","yellow","gray"])
    find.add_argument("--only", action="store_true")

    scrape = subparsers.add_parser("scrape", help="Run the scraper and write output files")
    scrape.add_argument("--config", help="Path to YAML config file")
    scrape.add_argument("--months", nargs="+", help="Month selectors such as this next")
    scrape.add_argument(
        "--format",
        dest="output_format",
        choices=["csv", "json", "both"],
        help="Output format to write",
    )
    scrape.add_argument("--output-dir", help="Directory for generated artifacts")
    scrape.add_argument("--timezone", help="Target timezone for converted event times")
    scrape.add_argument(
        "--currencies",
        nargs="+",
        help="Allowed currencies, for example USD EUR GBP CAD",
    )
    scrape.add_argument(
        "--impacts",
        nargs="+",
        help="Allowed impact levels, for example red orange gray",
    )
    scrape.add_argument(
        "--show-browser",
        action="store_true",
        help="Run with a visible browser instead of headless mode",
    )

    view = subparsers.add_parser("view", help="Launch the local Streamlit viewer")
    view.add_argument("--config", help="Path to YAML config file")
    view.add_argument("--output-dir", help="Directory containing generated artifacts")
    view.add_argument("--host", help=f"Viewer host, defaults to {DEFAULT_VIEWER_HOST}")
    view.add_argument("--port", type=int, help=f"Viewer port, defaults to {DEFAULT_VIEWER_PORT}")

    alerts = subparsers.add_parser("alerts-check", help="Evaluate rules and send alert notifications")
    alerts.add_argument("--config", help="Path to YAML config file")
    alerts.add_argument("--output-dir", help="Directory containing generated artifacts")
    alerts.add_argument("--rules-dir", help="Directory containing alert rule YAML files")
    alerts.add_argument("--state-dir", help="Directory for alert state")

    test_notify = subparsers.add_parser(
        "test-notify", help="Send a test message to all enabled connectors"
    )
    test_notify.add_argument("--config", help="Path to YAML config file")
    test_notify.add_argument("--output-dir", help="Directory containing generated artifacts")
    test_notify.add_argument("--rules-dir", help="Directory containing alert rule YAML files")
    test_notify.add_argument("--state-dir", help="Directory for alert state")

    schedule_info = subparsers.add_parser(
        "schedule-info", help="Print the effective cron expression"
    )
    schedule_info.add_argument("--config", help="Path to YAML config file")
    alert_schedule_info = subparsers.add_parser(
        "alerts-schedule-info", help="Print the effective alert cron expression"
    )
    alert_schedule_info.add_argument("--config", help="Path to YAML config file")
    return parser


def _prepare_args(argv: list[str] | None) -> list[str]:
    args = list(argv) if argv is not None else sys.argv[1:]
    if not args or args[0] not in {"scrape", "view", "alerts-check", "schedule-info", "alerts-schedule-info", "test-notify", *DATA_COMMANDS}:
        return ["scrape", *args]
    return args


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(_prepare_args(argv))
    if args.command in DATA_COMMANDS:
        return run_data_command(args)
    from .console import AppConsole
    from .runtime import (build_alert_options, build_run_options, current_alert_schedule,
                          current_schedule, load_env_file, resolve_config_path)
    from .scheduler import resolve_alert_schedule, resolve_schedule
    console = AppConsole()
    config_path = resolve_config_path(getattr(args, "config", None))
    env_path = load_env_file(config_path)
    if env_path.exists() and args.command not in {"schedule-info", "alerts-schedule-info"}:
        console.step(f"Loaded environment secrets from {env_path}")

    if args.command == "view":
        return run_viewer(console, args)

    if args.command == "schedule-info":
        cron_expression, preset = current_schedule(getattr(args, "config", None))
        print(resolve_schedule(preset, cron_expression))
        return 0

    if args.command == "alerts-schedule-info":
        cron_expression, preset = current_alert_schedule(getattr(args, "config", None))
        print(resolve_alert_schedule(preset, cron_expression))
        return 0

    if args.command == "test-notify":
        options = build_alert_options(args)
        from .alerts.notifiers import NotificationError, NotifierFactory

        factory = NotifierFactory(options)
        ids = factory.connector_ids()
        if not ids:
            console.step("No connectors are enabled. Enable at least one in config.yaml.")
            return 0
        all_ok = True
        for connector_id in ids:
            try:
                factory.send_raw(connector_id, "Forex Factory Alerts: test notification. Your setup is working.")
                console.step(f"ok  {connector_id}")
            except NotificationError as exc:
                console.error(f"fail  {connector_id}: {exc}")
                all_ok = False
        return 0 if all_ok else 1

    if args.command == "alerts-check":
        options = build_alert_options(args)
        from .alerts.service import AlertService

        return AlertService(console).run(options)

    options = build_run_options(args)
    from .service import ScrapeService

    return ScrapeService(console).run(options)


def run_viewer(console: AppConsole, args) -> int:
    from .runtime import build_view_options
    options = build_view_options(args)
    env = os.environ.copy()
    env["FF_CONFIG_PATH"] = str(options.config_path)
    env["FF_VIEWER_OUTPUT_DIR"] = str(options.output_dir)
    env["FF_ALERT_RULES_DIR"] = str(options.rules_dir)
    env["FF_ALERT_STATE_DIR"] = str(options.state_dir)
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(Path(__file__).resolve().parent / "viewer.py"),
        "--server.address",
        options.host,
        "--server.port",
        str(options.port),
    ]
    console.step(f"Launching viewer on http://{options.host}:{options.port}")
    try:
        return subprocess.call(command, env=env)
    except FileNotFoundError:
        console.error("Streamlit is not installed. Install requirements and try again.")
        return 1


def _cli_date(value: str):
    from datetime import date
    return date.today() if value == "today" else date.fromisoformat(value)


def run_data_command(args) -> int:
    import json
    from .configuration import find_configurations
    from .database import CalendarDatabase
    from .ingest import SourceError, parse_html
    from .pipeline import backfill, bootstrap, sync, update, validate
    db=CalendarDatabase()
    try:
        if args.command=="bootstrap": print(f"Imported {bootstrap(db,args.archive_file)} archive rows")
        elif args.command=="backfill": print(f"Upserted {backfill(db,_cli_date(args.start),_cli_date(args.end),args.html_directory,args.interactive_browser,args.browser_handoff)} rows")
        elif args.command=="update": print(f"Upserted {update(db)} weekly rows")
        elif args.command=="sync": print(json.dumps(sync(db,args.archive_file,args.interactive_browser,args.browser_handoff,args.force_refresh_start,args.yearly_excel_dir),indent=2))
        elif args.command=="validate":
            manifest,errors=validate(db,args.strict); print(json.dumps(manifest,indent=2)); return 1 if errors else 0
        elif args.command=="export": print(json.dumps(db.export(args.format),indent=2))
        elif args.command=="export-yearly-excel":
            manifest,errors=validate(db,strict=True)
            if errors: raise SourceError("validation failed: "+"; ".join(errors))
            from .excel_export import export_yearly_excel
            print(json.dumps([str(path) for path in export_yearly_excel(db,args.output_dir,manifest)],indent=2))
        elif args.command=="import-html":
            rows=parse_html(args.path.read_bytes(),args.path.resolve().as_uri(),args.period or "")
            db.upsert(rows)
            for period in sorted({r["date_et"][:7] for r in rows}): db.mark_period(period,"complete",sum(r["date_et"].startswith(period) for r in rows),source_type="saved_html")
            print(f"Imported {len(rows)} rows")
        elif args.command=="find-configuration":
            print(json.dumps(find_configurations(db.rows(),args.event,args.currencies,args.counted_impacts,args.only),indent=2))
        return 0
    except (SourceError,RuntimeError,ValueError,OSError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr); return 1
    finally: db.close()


if __name__ == "__main__":
    raise SystemExit(main())
