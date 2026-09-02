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

from .ingest import SourceError, VerificationPageError, parse_html

CALENDAR_URL = "https://www.forexfactory.com/calendar?month={month}"
LANDING_URL = "https://www.forexfactory.com/calendar"
HANDOFF_PROFILE = Path("data/chrome-handoff-profile")
LOCK_NAMES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


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
            "and its event rows are visible. Then return here and press Enter. "
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
        render_wait = float(os.environ.get("FF_HANDOFF_RENDER_SECONDS", "10"))
        while True:
            deadline = self.monotonic() + render_wait
            while True:
                html = self.driver.page_source
                try:
                    return html, parse_html(html, url, period)
                except VerificationPageError:
                    break
                except SourceError as exc:
                    # Only transient empty/not-yet-rendered documents are polled.
                    # Recognized malformed event rows fail immediately.
                    transient = str(exc) in {
                        "page contains no recognizable calendar rows",
                        "calendar rows contained no events",
                    }
                    if not transient or self.monotonic() >= deadline:
                        raise
                    self.sleep(0.25)
            self._wait_for_user(
                f"Access paused while retrieving {period}. Leave this same Chrome window open, "
                "establish access manually, wait until event rows are visible, then press Enter "
                "to retry this month. Press Ctrl-C to cancel."
            )
            # Do not navigate away or create another session. The user has
            # cleared access in this tab; poll that same month again.

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
