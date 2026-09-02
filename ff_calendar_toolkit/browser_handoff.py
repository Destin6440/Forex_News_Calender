"""Safe handoff from an ordinary Chrome process to Selenium.

This module deliberately does not automate security challenges.  Chrome is
started independently, the user decides when the ordinary page is accessible,
and only then is ChromeDriver attached to the localhost debugging endpoint.
"""
from __future__ import annotations

import os
import platform
import re
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from .ingest import (SourceError, VerificationPageError, calendar_row_counts,
                     month_data_identity_label, parse_html)

CALENDAR_URL = "https://www.forexfactory.com/calendar?month={month}"
LANDING_URL = "https://www.forexfactory.com/calendar"
HANDOFF_PROFILE = Path("data/chrome-handoff-profile")
LOCK_NAMES = ("SingletonLock", "SingletonCookie", "SingletonSocket")

SCROLL_METRICS_SCRIPT = r"""
const calendars = [...document.querySelectorAll('.calendar, table.calendar__table, .calendar__table')];
let node = calendars[0] || document.scrollingElement || document.documentElement;
for (let candidate = node; candidate; candidate = candidate.parentElement) {
  if (candidate.scrollHeight > candidate.clientHeight + 1 &&
      ['auto', 'scroll'].includes(getComputedStyle(candidate).overflowY)) {
    node = candidate; break;
  }
}
if (!(node.scrollHeight > node.clientHeight + 1)) {
  node = document.scrollingElement || document.documentElement;
}
return {top: node.scrollTop || window.scrollY || 0,
        height: node.scrollHeight || document.documentElement.scrollHeight,
        client: node.clientHeight || window.innerHeight,
        document: node === document.scrollingElement || node === document.documentElement};
"""

SCROLL_TO_SCRIPT = r"""
const target = arguments[0];
const calendars = [...document.querySelectorAll('.calendar, table.calendar__table, .calendar__table')];
let node = calendars[0] || document.scrollingElement || document.documentElement;
for (let candidate = node; candidate; candidate = candidate.parentElement) {
  if (candidate.scrollHeight > candidate.clientHeight + 1 &&
      ['auto', 'scroll'].includes(getComputedStyle(candidate).overflowY)) {
    node = candidate; break;
  }
}
if (!(node.scrollHeight > node.clientHeight + 1)) node = document.scrollingElement || document.documentElement;
if (node === document.scrollingElement || node === document.documentElement) window.scrollTo(0, target);
else node.scrollTop = target;
return true;
"""


class ChromeHandoff:
    """Manage one externally launched Chrome and one attached WebDriver."""

    def __init__(self, profile: Path = HANDOFF_PROFILE, *, input_fn=input,
                 output=print, popen=subprocess.Popen, ps=None, urlopen=urllib.request.urlopen,
                 driver_factory=None, options_factory=None, sleep=time.sleep,
                 monotonic=time.monotonic, chrome_path: str | None = None) -> None:
        self.profile = profile.resolve()
        self.input = input_fn
        self.output = output
        self.popen = popen
        self.ps = ps or self._process_list
        self.urlopen = urlopen
        self.driver_factory = driver_factory
        self.options_factory = options_factory
        self.sleep = sleep
        self.monotonic = monotonic
        self.chrome_path = chrome_path
        self.process = None
        self.port: int | None = None
        self.driver = None
        self.launched_by_us = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_exc):
        self.close()

    @staticmethod
    def _process_list() -> str:
        return subprocess.check_output(["ps", "-axo", "pid=,command="], text=True)

    def _dedicated_processes(self) -> list[tuple[int, str, int | None]]:
        result = []
        profile_flag = f"--user-data-dir={self.profile}"
        for line in self.ps().splitlines():
            if profile_flag not in line:
                continue
            match = re.match(r"\s*(\d+)\s+(.*)", line)
            if not match:
                continue
            port_match = re.search(r"--remote-debugging-port=(\d+)", match.group(2))
            result.append((int(match.group(1)), match.group(2), int(port_match.group(1)) if port_match else None))
        return result

    @staticmethod
    def _available_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _chrome_executable(self) -> str:
        if self.chrome_path:
            return self.chrome_path
        if platform.system() == "Darwin":
            path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            if not Path(path).is_file():
                raise SourceError(
                    "Google Chrome was not found at /Applications/Google Chrome.app. "
                    "Install it in Applications, then rerun this command."
                )
            return path
        for path in ("/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium"):
            if Path(path).is_file():
                return path
        raise SourceError("Google Chrome was not found (expected /Applications/Google Chrome.app on macOS)")

    def _debugger_ready(self) -> bool:
        try:
            with self.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1) as response:
                return bool(response.read())
        except Exception:
            return False

    def start(self) -> None:
        if self.port is not None:
            return
        processes = self._dedicated_processes()
        debug_processes = [item for item in processes if item[2] is not None]
        if debug_processes:
            ports = {item[2] for item in debug_processes}
            if len(ports) != 1:
                raise SourceError("multiple dedicated handoff Chrome debugger ports are active")
            self.port = debug_processes[0][2]
            if not self._debugger_ready():
                raise SourceError(
                    "The dedicated Chrome process exists, but its localhost debugger is not responding. "
                    "Close that dedicated window and retry."
                )
            self.output(f"Reusing dedicated Chrome handoff profile on 127.0.0.1:{self.port}.")
            return
        if processes:
            raise SourceError(
                "The dedicated handoff profile is already in use by Chrome without remote debugging. "
                "Close that dedicated Chrome window and retry; no profile files were changed."
            )

        self.profile.mkdir(parents=True, exist_ok=True)
        # Process inspection above positively established that this dedicated
        # profile is unused. Remove only Chrome's known stale singleton markers.
        for name in LOCK_NAMES:
            path = self.profile / name
            if path.is_symlink() or path.is_file() or path.exists():
                path.unlink(missing_ok=True)
        self.port = self._available_port()
        command = [
            self._chrome_executable(),
            f"--user-data-dir={self.profile}",
            f"--remote-debugging-port={self.port}",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run",
            "--no-default-browser-check",
            LANDING_URL,
        ]
        self.process = self.popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.launched_by_us = True
        try:
            for _ in range(100):
                if self._debugger_ready():
                    break
                if self.process.poll() is not None:
                    raise SourceError("ordinary Chrome exited before its local debugger became ready")
                self.sleep(0.1)
            else:
                raise SourceError("ordinary Chrome started, but its localhost debugger did not become ready")
        except BaseException:
            self._terminate_owned_process()
            self.port = None
            raise

    def _wait_for_user(self, message: str) -> None:
        self.output(message)
        try:
            self.input()
        except EOFError as exc:
            raise SourceError("browser handoff cancelled because terminal input closed") from exc

    def _attach(self) -> None:
        if self.driver is not None:
            return
        self._wait_for_user(
            "Use the open Chrome window normally. Wait until the Forex Factory calendar "
            "and its event rows are visible. Before pressing Enter, make sure Forex Factory "
            "is displaying all currencies and all impact levels, with no research-specific "
            "calendar filter active. Then return here and press Enter. "
            "Press Ctrl-C to cancel."
        )
        if self.options_factory is None:
            from selenium.webdriver.chrome.options import Options
            options = Options()
        else:
            options = self.options_factory()
        options.debugger_address = f"127.0.0.1:{self.port}"
        if self.driver_factory is None:
            from selenium import webdriver
            self.driver = webdriver.Chrome(options=options)
        else:
            self.driver = self.driver_factory(options)

    def retrieve(self, month) -> tuple[str, list[dict]]:
        self.start()
        self._attach()
        period = month.strftime("%Y-%m")
        url = CALENDAR_URL.format(month=month.strftime("%b.%Y").lower())
        self.driver.get(url)
        self.sleep(float(os.environ.get("FF_PAGE_WAIT_SECONDS", "3")))
        max_duration = float(os.environ.get("FF_HANDOFF_SWEEP_SECONDS", "60"))
        interval = float(os.environ.get("FF_HANDOFF_SCROLL_INTERVAL_SECONDS", "0.25"))
        overlap = float(os.environ.get("FF_HANDOFF_SCROLL_OVERLAP", "0.35"))
        if max_duration <= 0 or interval < 0 or not 0 < overlap < 1:
            raise SourceError("invalid browser sweep settings: duration must be positive, interval nonnegative, and overlap between 0 and 1")
        while True:
            try:
                return self._sweep_month(url, period, max_duration, interval, overlap)
            except VerificationPageError:
                pass
            self._wait_for_user(
                f"Access paused while retrieving {period}. Leave this same Chrome window open, "
                "establish access manually, wait until event rows are visible, then press Enter "
                "to retry this month. Press Ctrl-C to cancel."
            )
            # Do not navigate away or create another session. The user has
            # cleared access in this tab; poll that same month again.

    def _scroll_metrics(self) -> dict[str, float]:
        execute = getattr(self.driver, "execute_script", None)
        if execute is None:  # Small third-party/fake drivers and static pages.
            return {"top": 0.0, "height": 0.0, "client": 0.0}
        raw = execute(SCROLL_METRICS_SCRIPT) or {}
        return {name: float(raw.get(name, 0) or 0) for name in ("top", "height", "client")}

    def _scroll_to(self, position: float) -> None:
        execute = getattr(self.driver, "execute_script", None)
        if execute is not None:
            execute(SCROLL_TO_SCRIPT, max(0, position))

    @staticmethod
    def _event_identity(event: dict) -> tuple:
        # Only Month Data labels extend the legacy clockless identity. Other
        # non-clock labels deliberately retain the established None component.
        non_clock_label = None
        if event.get("time_et") is None:
            non_clock_label = month_data_identity_label(str(event.get("raw_time") or ""))
        return (event["date_et"], event.get("time_et"), non_clock_label,
                event["currency"], event["event_name_normalized"])

    def _sweep_month(self, url: str, period: str, max_duration: float,
                     interval: float, overlap: float) -> tuple[str, list[dict]]:
        deadline = self.monotonic() + max_duration
        self._scroll_to(0)
        accumulated: dict[str, dict] = {}
        identities: dict[tuple, set[str]] = {}
        progress: list[int] = []
        grew_after_initial = False
        bottom_stable_passes = 0
        last_html = ""
        materialized = placeholders = 0
        final_position = 0.0
        wait_for_render = False

        while self.monotonic() < deadline:
            if wait_for_render:
                self.sleep(interval)
            wait_for_render = True
            last_html = self.driver.page_source
            try:
                snapshot = parse_html(last_html, url, period)
            except VerificationPageError:
                raise
            except SourceError as exc:
                # Rendering may initially expose only structural/blank rows;
                # populated malformed rows are never retried.
                if str(exc) not in {"page contains no recognizable calendar rows", "calendar rows contained no events"}:
                    raise
                snapshot = []
            _rows, materialized, placeholders = calendar_row_counts(last_html)
            before = len(accumulated)
            for event in snapshot:
                identity = self._event_identity(event)
                key = event["event_key"]
                if key in accumulated:
                    accumulated[key] = event
                    continue

                matching_keys = identities.setdefault(identity, set())
                if event.get("source_event_id"):
                    # Replace only derived versions of this natural identity.
                    # Different stable source IDs always represent distinct
                    # upstream rows and must coexist even when all other fields
                    # are identical.
                    derived_keys = [old_key for old_key in matching_keys
                                    if not accumulated[old_key].get("source_event_id")]
                    for old_key in derived_keys:
                        accumulated.pop(old_key)
                        matching_keys.remove(old_key)
                elif any(accumulated[old_key].get("source_event_id")
                         for old_key in matching_keys):
                    # A richer source-ID record from another viewport already
                    # represents this derived event.
                    continue
                accumulated[key] = event
                matching_keys.add(key)
            if len(accumulated) > before:
                if progress:
                    grew_after_initial = True
                progress.append(len(accumulated))
                self.output(f"{period} virtualized sweep: {' → '.join(map(str, progress))} events")

            metrics = self._scroll_metrics()
            top, height, client = metrics["top"], metrics["height"], metrics["client"]
            final_position = top
            bottom = max(0.0, height - client)
            if height <= client + 1:  # Ordinary non-virtualized document.
                if accumulated:
                    return last_html, list(accumulated.values())
                continue
            at_bottom = top >= bottom - 1
            if at_bottom:
                # Always request bottom once more: materialization can increase
                # scrollHeight, and only unchanged bottom passes are stable.
                if len(accumulated) == before:
                    bottom_stable_passes += 1
                else:
                    bottom_stable_passes = 0
                self._scroll_to(bottom)
                if bottom_stable_passes >= 2 and (not placeholders or grew_after_initial):
                    return last_html, list(accumulated.values())
            else:
                bottom_stable_passes = 0
                step = max(1.0, client * (1.0 - overlap))
                self._scroll_to(min(bottom, top + step))

        raise SourceError(
            f"{period} virtualized calendar sweep timed out after {max_duration:g}s: "
            f"accumulated events={len(accumulated)}, materialized rows={materialized}, "
            f"placeholder rows={placeholders}, final scroll position={final_position:g}"
        )

    def _terminate_owned_process(self) -> None:
        if not self.launched_by_us or self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.output("Chrome did not exit after a clean shutdown request; leaving it running.")

    def close(self) -> None:
        if self.driver is not None:
            try:
                if self.launched_by_us:
                    self.driver.quit()
                else:
                    # quit() can close an attached Chrome. Stop only the local
                    # ChromeDriver service when this Chrome is externally owned.
                    service = getattr(self.driver, "service", None)
                    if service is not None:
                        service.stop()
            except Exception as exc:
                self.output(f"Could not detach Selenium cleanly: {exc}")
            finally:
                self.driver = None
        self._terminate_owned_process()
        self.process = None
