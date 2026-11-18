"""Read who is in a Google Meet from its pre-join ("waiting") screen, without joining.

A headless Chrome, signed in to Google with its own profile directory, keeps one tab open per
watched meeting and reads lines like "Dan Burtenshaw and 2 others are in this call".
It never clicks Join or Ask to join, and camera and microphone permission requests are denied.

This depends on Meet's page text, so it can break when Google changes the page.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("meeting-join-alert")

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
LOAD_GRACE_SECONDS = 45  # how long a fresh tab may show nothing recognisable before we call it "no info"

# Chrome encrypts cookies with a Keychain key; Playwright launches Chrome with a mock keychain, so the
# sign-in must use the same flag or the headless browser can't read the session cookies.
COMMON_ARGS = ["--use-mock-keychain", "--no-first-run", "--no-default-browser-check", "--lang=en-GB"]

IN_CALL_RE = re.compile(r"^(.+?) (?:is|are) in (?:this|the) call\b", re.I | re.M)
OTHERS_RE = re.compile(r"(?:,\s*)?(?:and\s+)?(\d+)\s+(?:others?|more)\s*$", re.I)
NAME_SPLIT_RE = re.compile(r",\s*(?:and\s+)?|\s+and\s+", re.I)
EMPTY_MARKERS = ("no one else is here", "no one else is in this call", "no one is in this call")
ME_ELSEWHERE_MARKERS = ("on another device", "you're already in this call", "you are already in this call",
                        "switch here")
BLOCKED_MARKERS = ("you can't join this video call", "check your meeting code", "this meeting has ended",
                   "meeting code has expired", "you can't create a meeting yourself")


@dataclass
class Reading:
    status: str  # "ok", "empty", "me_elsewhere", "no_info", "blocked", "signed_out"
    names: list[str] = field(default_factory=list)
    others: int = 0
    detail: str = ""


def parse(text: str, url: str) -> Reading | None:
    """Interpret the waiting-screen text. None means nothing recognisable yet (still loading)."""
    if "accounts.google.com" in url:
        return Reading("signed_out")
    low = text.lower()
    for m in BLOCKED_MARKERS:
        if m in low:
            return Reading("blocked", detail=m)
    match = IN_CALL_RE.search(text)
    if not match:
        if any(m in low for m in ME_ELSEWHERE_MARKERS):
            return Reading("me_elsewhere", detail=snippet(text))
        if any(m in low for m in EMPTY_MARKERS):
            return Reading("empty")
        return None
    who = match.group(1).strip()
    others = 0
    om = OTHERS_RE.search(who)
    if om:
        others = int(om.group(1))
        who = who[: om.start()].strip()
    names = [n.strip() for n in NAME_SPLIT_RE.split(who) if n.strip()]
    return Reading("ok", names=names, others=others)


def snippet(text: str) -> str:
    """The lines of a page that look like they're about who is in the call, for diagnosing parse misses."""
    keep = [ln.strip() for ln in text.splitlines()
            if re.search(r"\b(call|here|join|waiting|host|meeting)\b", ln, re.I) and len(ln) < 120]
    return " | ".join(keep[:6])


def chrome_version() -> str:
    try:
        out = subprocess.run([CHROME, "--version"], capture_output=True, text=True, timeout=10).stdout
        return re.search(r"(\d+)\.", out).group(1)
    except Exception:
        return "140"


def open_sign_in_window(profile_dir: Path) -> None:
    """Open a normal (not automated) Chrome window on the dedicated profile, and wait until it's quit.
    The headless browser must not be running on the same profile at the time."""
    profile_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(profile_dir, 0o700)
    subprocess.run([CHROME, f"--user-data-dir={profile_dir}", *COMMON_ARGS, "https://accounts.google.com/"])


def login(profile_dir: Path) -> None:
    print("A separate Chrome window will open. Sign in to your Google account there,\n"
          "open https://meet.google.com once to check you're signed in, then quit that Chrome with Cmd-Q.")
    open_sign_in_window(profile_dir)
    print(f"Saved sign-in to {profile_dir}. A running watcher picks it up on its next Meet meeting.")


class WaitingScreen:
    """Keeps a headless Chrome with one tab per watched meeting. Closes Chrome when no tabs are open."""

    def __init__(self, profile_dir: Path):
        self.profile_dir = profile_dir
        self._pw = None
        self._ctx = None
        self.tabs: dict[str, tuple[object, float]] = {}  # key -> (page, opened_at)

    @property
    def signed_in(self) -> bool:
        return (self.profile_dir / "Default" / "Cookies").exists()

    def _context(self):
        if self._ctx is None:
            from playwright.sync_api import sync_playwright

            self._pw = sync_playwright().start()
            major = chrome_version()
            self._ctx = self._pw.chromium.launch_persistent_context(
                str(self.profile_dir),
                channel="chrome",
                headless=True,
                args=[*COMMON_ARGS, "--mute-audio", "--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
                locale="en-GB",
                viewport={"width": 1280, "height": 800},
                user_agent=(f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                            f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"),
                permissions=[],  # deny camera / microphone
            )
            log.info("Started headless Chrome for Meet waiting screens")
        return self._ctx

    def read(self, key: str, url: str) -> Reading | None:
        """Current reading for a meeting, opening its tab on first call. None while the page is loading."""
        if key not in self.tabs:
            page = self._context().new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            self.tabs[key] = (page, time.time())
            return None
        page, opened = self.tabs[key]
        reading = parse(page.inner_text("body", timeout=10_000), page.url)
        if reading is None and time.time() - opened > LOAD_GRACE_SECONDS:
            return Reading("no_info", detail=snippet(page.inner_text("body", timeout=10_000)))
        return reading

    def text(self, key: str) -> str:
        page, _ = self.tabs[key]
        return page.inner_text("body", timeout=10_000)

    def screenshot(self, key: str, path: Path) -> None:
        page, _ = self.tabs[key]
        page.screenshot(path=str(path))

    def close(self, key: str) -> None:
        tab = self.tabs.pop(key, None)
        if tab:
            try:
                tab[0].close()
            except Exception:
                pass
        if not self.tabs:
            self.shutdown()

    def shutdown(self) -> None:
        for page, _ in self.tabs.values():
            try:
                page.close()
            except Exception:
                pass
        self.tabs.clear()
        if self._ctx is not None:
            try:
                self._ctx.close()
                self._pw.stop()
            except Exception:
                pass
            self._ctx = self._pw = None
            log.info("Stopped headless Chrome")
