#!/usr/bin/env python3
"""Alert on macOS when someone joins a Google Meet or Zoom meeting that is on your Google Calendar.

Every `poll_seconds` it:
  1. lists calendar events that start within `minutes_before_start` or are in progress,
  2. finds the Meet code or Zoom meeting ID on each one,
  3. reads who is in the meeting: Meet from the pre-join "waiting screen" in a headless,
     signed-in Chrome (needs --meet-login), Zoom from the Zoom API,
  4. posts a notification for each new person, and goes quiet once you have joined yourself.

Usage:
  meeting_join_alert.py --auth         one-off Google sign-in (run in a terminal)
  meeting_join_alert.py --test-notify  check notifications work
  meeting_join_alert.py --once         one poll with verbose output
  meeting_join_alert.py --tomorrow     list tomorrow's meetings and whether each can be watched
  meeting_join_alert.py --meet-login   sign in to Google in the browser used for Meet waiting screens
  meeting_join_alert.py --meet-peek URL  show what the Meet waiting screen reports for one meeting
  meeting_join_alert.py                run forever (what launchd runs)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from google.auth.exceptions import TransportError
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

import meet_waiting_screen

HERE = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("MJA_CONFIG", HERE / "config.json"))
TOKEN_PATH = HERE / "google_token.json"
ALERTED_PATH = HERE / "alerted.json"  # meetings already alerted on, so a restart doesn't alert again

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
ZOOM_API = "https://api.zoom.us/v2"

MEET_RE = re.compile(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", re.I)
ZOOM_RE = re.compile(r"https?://[\w.-]*zoom\.us/(?:j|w|s)/(\d{9,11})", re.I)
TEAMS_RE = re.compile(r"https?://teams\.(?:microsoft\.com/(?:l/meetup-join|meet)|live\.com/meet)[^\s\"'<>)]*", re.I)

DEFAULTS = {
    "google_client_secret": "client_secret.json",
    "calendar_ids": ["primary"],
    "meet_profile_dir": "meet_profile",  # Chrome profile used to read Meet waiting screens
    "poll_seconds": 30,
    "minutes_before_start": 10,
    # Keep watching a meeting until someone else joins or this many minutes after its start.
    "watch_minutes_after_start": 5,
    "my_names": [],
    "sound": "Glass",
    "style": "both",  # "alert" = large centred window with Join button, "banner" = standard notification, "both"
    "alert_timeout_seconds": 300,  # alert closes itself after this long (0 = stays until dismissed)
    "zoom": None,
    # Zoom and Teams meetings get a "starts in 1 minute" alert, since we can't see who's in them.
    # Seconds before the start to show it (0 = off).
    "reminder_seconds_before": 60,
}

log = logging.getLogger("meeting-join-alert")


# ---------------------------------------------------------------- config / auth

def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text()))
    cfg["my_names"] = [n.strip().lower() for n in cfg["my_names"] if n.strip()]
    return cfg


def waiting_screen(cfg: dict) -> meet_waiting_screen.WaitingScreen | None:
    """The waiting-screen reader, if you've signed in with --meet-login."""
    screen = meet_waiting_screen.WaitingScreen(HERE / cfg["meet_profile_dir"])
    if not screen.signed_in:
        log.warning("The Meet browser isn't signed in - run --meet-login to watch Meet meetings")
        return None
    return screen


def google_session(cfg: dict, interactive: bool = False) -> AuthorizedSession:
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not (interactive or sys.stdin.isatty()):
            raise SystemExit("No valid Google token - run `meeting_join_alert.py --auth` in a terminal first.")
        flow = InstalledAppFlow.from_client_secrets_file(str(HERE / cfg["google_client_secret"]), SCOPES)
        creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json())
    os.chmod(TOKEN_PATH, 0o600)
    return AuthorizedSession(creds)


# ---------------------------------------------------------------- calendar

def current_events(gs: AuthorizedSession, cfg: dict) -> list[dict]:
    """Timed events that are in progress or start within the lead window, excluding ones you declined."""
    now = datetime.now(timezone.utc)
    return events_between(gs, cfg, now, now + timedelta(minutes=cfg["minutes_before_start"]))


def events_between(gs: AuthorizedSession, cfg: dict, start: datetime, end: datetime) -> list[dict]:
    """Timed events that overlap [start, end), excluding ones you declined."""
    params = {
        "timeMin": start.isoformat(),  # event ends after this
        "timeMax": end.isoformat(),  # event starts before this
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 50,
    }
    events = []
    for cal_id in cfg["calendar_ids"]:
        r = gs.get(f"{CALENDAR_API}/calendars/{requests.utils.quote(cal_id)}/events", params=params, timeout=20)
        r.raise_for_status()
        for ev in r.json().get("items", []):
            if ev.get("status") == "cancelled" or "dateTime" not in ev.get("start", {}):
                continue
            me = next((a for a in ev.get("attendees", []) if a.get("self")), None)
            if me and me.get("responseStatus") == "declined":
                continue
            events.append(ev)
    return events


def find_meeting(ev: dict) -> tuple[str, str | None, str | None] | None:
    """Return (kind, id, join_url) for the video meeting on an event, or None."""
    cd = ev.get("conferenceData") or {}
    if cd.get("conferenceSolution", {}).get("key", {}).get("type") == "hangoutsMeet" and cd.get("conferenceId"):
        return "meet", cd["conferenceId"], ev.get("hangoutLink")

    texts = [ep.get("uri", "") for ep in cd.get("entryPoints", [])]
    texts += [ev.get("hangoutLink", ""), ev.get("location", ""), ev.get("description", "")]
    blob = "\n".join(t for t in texts if t)

    m = MEET_RE.search(blob)
    if m:
        return "meet", m.group(1).lower(), f"https://meet.google.com/{m.group(1).lower()}"
    m = ZOOM_RE.search(blob)
    if m:
        url = re.search(r"https?://[\w.-]*zoom\.us/[^\s\"'<>)]+", blob)
        return "zoom", m.group(1), url.group(0) if url else None
    m = TEAMS_RE.search(blob)
    if m:
        return "teams", None, m.group(0)
    return None


class NotAvailable(Exception):
    """We can't see who is in this meeting (not set up, not your Zoom account, Meet blocked us)."""


# ---------------------------------------------------------------- Zoom

class Zoom:
    """Server-to-Server OAuth client. Only sees meetings hosted on your own Zoom account."""

    def __init__(self, conf: dict):
        self.conf = conf
        self.token = None
        self.expires = 0.0
        self.dashboard_ok = True

    def _headers(self) -> dict:
        if time.time() > self.expires - 60:
            r = requests.post(
                "https://zoom.us/oauth/token",
                params={"grant_type": "account_credentials", "account_id": self.conf["account_id"]},
                auth=(self.conf["client_id"], self.conf["client_secret"]),
                timeout=20,
            )
            r.raise_for_status()
            body = r.json()
            self.token, self.expires = body["access_token"], time.time() + body["expires_in"]
        return {"Authorization": f"Bearer {self.token}"}

    def status(self, meeting_id: str) -> str:
        r = requests.get(f"{ZOOM_API}/meetings/{meeting_id}", headers=self._headers(), timeout=20)
        if r.status_code in (400, 404):
            raise NotAvailable("not a meeting on your Zoom account")
        r.raise_for_status()
        return r.json().get("status", "waiting")  # "waiting" or "started"

    def participants(self, meeting_id: str) -> list[tuple[str, str]] | None:
        """Live participant list via the Dashboard API (Business plan+). None if unavailable."""
        if not self.dashboard_ok:
            return None
        r = requests.get(
            f"{ZOOM_API}/metrics/meetings/{meeting_id}/participants",
            headers=self._headers(),
            params={"type": "live", "page_size": 100},
            timeout=20,
        )
        if r.status_code in (400, 401, 403):
            log.info("Zoom Dashboard API unavailable (%s) - falling back to 'meeting started' alerts", r.status_code)
            self.dashboard_ok = False
            return None
        if r.status_code == 404:
            return []  # not live yet
        r.raise_for_status()
        return [
            (str(p.get("id") or p.get("user_id") or p.get("user_name")), p.get("user_name") or "Someone")
            for p in r.json().get("participants", [])
            if not p.get("leave_time")
        ]


# ---------------------------------------------------------------- notifications

def notify(title: str, message: str, url: str | None, cfg: dict) -> None:
    log.info("NOTIFY %s - %s", title, message)
    style = cfg.get("style")
    if style in ("banner", "both"):
        show_banner(title, message, url, cfg["sound"])
    if style in ("alert", "both"):
        show_alert(title, message, url, cfg, play_sound=(style == "alert"))


def show_alert(title: str, message: str, url: str | None, cfg: dict, play_sound: bool = True) -> None:
    """Large centred alert window with Join / Dismiss buttons. Runs in the background so polling continues."""
    sound = Path(f"/System/Library/Sounds/{cfg['sound']}.aiff")
    if play_sound and sound.exists():
        subprocess.Popen(["afplay", str(sound)])
    timeout = int(cfg.get("alert_timeout_seconds") or 0)
    giving_up = f" giving up after {timeout}" if timeout > 0 else ""
    buttons = '{"Dismiss", "Join"} default button "Join"' if url else '{"OK"} default button "OK"'
    # args passed via argv so no quoting problems
    script = [
        "-e", "on run argv",
        "-e", "activate",
        "-e", f"set r to display alert (item 1 of argv) message (item 2 of argv) buttons {buttons}{giving_up}",
        "-e", 'if button returned of r is "Join" then open location (item 3 of argv)',
        "-e", "end run",
    ]
    subprocess.Popen(["osascript", *script, title, message, url or ""],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def show_banner(title: str, message: str, url: str | None, sound: str) -> None:
    tn = shutil.which("terminal-notifier")
    if tn:
        cmd = [tn, "-title", title, "-message", message, "-sound", sound, "-group", title]
        if url:
            cmd += ["-open", url]
        subprocess.run(cmd, check=False)
        return
    # osascript fallback: args passed via argv so no quoting problems
    script = [
        "-e", "on run argv",
        "-e", "display notification (item 2 of argv) with title (item 1 of argv) sound name (item 3 of argv)",
        "-e", "end run",
    ]
    subprocess.run(["osascript", *script, title, message, sound], check=False)


# ---------------------------------------------------------------- main loop

class Watcher:
    def __init__(self, cfg: dict, gs: AuthorizedSession):
        self.cfg = cfg
        self.gs = gs
        self.zoom = Zoom(cfg["zoom"]) if cfg.get("zoom") else None
        self.screen = waiting_screen(cfg)
        self.state: dict[str, dict] = {}
        self.alerted: dict[str, float] = {}
        if ALERTED_PATH.exists():
            try:
                cutoff = time.time() - 2 * 86400
                self.alerted = {k: t for k, t in json.loads(ALERTED_PATH.read_text()).items() if t > cutoff}
            except (ValueError, AttributeError):
                pass

    def is_me(self, name: str) -> bool:
        return name.strip().lower() in self.cfg["my_names"]

    def tick(self) -> None:
        live_keys = set()
        for ev in current_events(self.gs, self.cfg):
            meeting = find_meeting(ev)
            if not meeting:
                continue
            kind, mid, url = meeting
            key = f"{ev['id']}|{kind}|{mid}"
            live_keys.add(key)
            title = ev.get("summary") or "(untitled meeting)"
            if key not in self.state:
                log.info("Watching '%s' (%s)", title, kind)
            st = self.state.setdefault(key, {"key": key, "done": key in self.alerted, "started": False})
            start = datetime.fromisoformat(ev["start"]["dateTime"].replace("Z", "+00:00"))
            cutoff = start + timedelta(minutes=self.cfg["watch_minutes_after_start"])
            if not st["done"] and datetime.now(timezone.utc) > cutoff:
                log.info("Stopped watching '%s': nobody else joined by %s", title, cutoff.astimezone().strftime("%H:%M"))
                st["done"] = True
                if self.screen:
                    self.screen.close(key)
            if kind in ("zoom", "teams"):
                self.remind(ev, key, kind, url, title)
            if st["done"]:
                continue
            try:
                self.check(ev, key, kind, mid, url, title, st)
            except NotAvailable as e:
                log.info("Can't watch '%s' (%s): %s", title, kind, e)
                st["done"] = True
            if st["done"] and self.screen:
                self.screen.close(key)
        # forget events that have ended
        for key in set(self.state) - live_keys:
            del self.state[key]
            if self.screen:
                self.screen.close(key)

    def remind(self, ev: dict, key: str, kind: str, url: str | None, title: str) -> None:
        """Alert shortly before a Zoom/Teams meeting starts, once. Skipped if we only notice it well after the start."""
        lead = int(self.cfg.get("reminder_seconds_before") or 0)
        rkey = key + "|reminder"
        if lead <= 0 or rkey in self.alerted:
            return
        start = datetime.fromisoformat(ev["start"]["dateTime"].replace("Z", "+00:00"))
        to_go = (start - datetime.now(timezone.utc)).total_seconds()
        if to_go > lead or to_go < -120:
            return
        when = "now" if to_go <= 0 else f"in {max(1, round(to_go / 60))} minute{'s' if round(to_go / 60) > 1 else ''}"
        notify(f"{kind.capitalize()} meeting starts {when}", title, url, self.cfg)
        self.alerted[rkey] = time.time()
        ALERTED_PATH.write_text(json.dumps(self.alerted))

    def check_waiting_screen(self, key: str, url: str, title: str, st: dict) -> None:
        if not self.screen:
            raise NotAvailable("waiting screen not set up - run --meet-login")
        from playwright.sync_api import Error as PlaywrightError

        try:
            r = self.screen.read(key, url)
        except PlaywrightError as e:
            log.warning("Waiting screen for '%s' failed, will reopen: %s", title, str(e).splitlines()[0])
            self.screen.close(key)
            return
        if r is None:
            return  # still loading
        log.debug("waiting screen '%s': %s", title, r)
        if r.status == "signed_out":
            raise NotAvailable("the Meet browser is signed out - run --meet-login")
        if r.status == "blocked":
            raise NotAvailable(f"Meet says '{r.detail}'")
        if r.status == "no_info":
            if not st.get("no_info_logged"):
                st["no_info_logged"] = True
                log.info("Waiting screen for '%s' doesn't show who's in the call (yet). Page says: %s",
                         title, r.detail or "(nothing relevant)")
            return
        if r.status == "me_elsewhere":
            if not st.get("me_elsewhere_logged"):
                st["me_elsewhere_logged"] = True
                log.info("Waiting screen for '%s' says you're in the call elsewhere - still watching. Page says: %s",
                         title, r.detail or "(nothing relevant)")
            return
        names = [n for n in r.names if not self.is_me(n)]
        if names or r.others:
            self.announce(names, r.others, title, url, st)

    def check(self, ev: dict, key: str, kind: str, mid: str | None, url: str | None, title: str,
              st: dict) -> None:
        if kind == "teams":
            raise NotAvailable("no Teams API - start reminder only")
        if kind == "meet":
            return self.check_waiting_screen(key, url, title, st)
        if kind == "zoom":
            if not self.zoom:
                raise NotAvailable("no Zoom credentials in config")
            status = self.zoom.status(mid)
            people = self.zoom.participants(mid)
            if people is None:  # no Dashboard API: best we can do is "it has started"
                if status == "started" and not st["started"]:
                    st["started"] = True
                    notify("Zoom meeting started", f"Someone is in '{title}'", url, self.cfg)
                return
        else:
            return

        log.debug("%s '%s': %s", kind, title, [n for _, n in people])
        others = [n for _, n in people if not self.is_me(n)]
        if others:
            self.announce(others, 0, title, url, st)

    def announce(self, names: list[str], others: int, title: str, url: str | None, st: dict) -> None:
        """One alert per meeting, at the first arrival; then stop watching it."""
        count = len(names) + others
        if others:
            who = f"{', '.join(names)} and {others} other{'s' if others > 1 else ''}" if names else f"{others} people"
        else:
            who = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
        notify(f"{who} {'is' if count == 1 else 'are'} in the call", title, url, self.cfg)
        st["done"] = True
        self.alerted[st["key"]] = time.time()
        ALERTED_PATH.write_text(json.dumps(self.alerted))


def transient_error(e: Exception) -> str | None:
    """One-line summary if `e` is a network blip or a temporary server error, else None."""
    if isinstance(e, requests.HTTPError) and e.response is not None:
        code = e.response.status_code
        if code == 429 or code >= 500:
            return f"{code} {e.response.reason} from {requests.utils.urlparse(e.response.url).hostname}"
        return None
    if isinstance(e, (requests.ConnectionError, requests.Timeout, TransportError)):
        host = getattr(getattr(e, "request", None), "url", None)
        host = requests.utils.urlparse(host).hostname if host else "Google"
        kind = "timed out" if isinstance(e, requests.Timeout) or "timed out" in str(e) else "network unavailable"
        return f"{kind} talking to {host}"
    return None


def list_tomorrow(gs: AuthorizedSession, cfg: dict) -> None:
    screen = waiting_screen(cfg)
    if not screen:
        print("Meet waiting screen not signed in - run --meet-login\n")
    start = (datetime.now().astimezone() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    events = events_between(gs, cfg, start, start + timedelta(days=1))
    print(f"Calendars {cfg['calendar_ids']} on {start:%A %d %B}: {len(events)} timed event(s)\n")
    for ev in events:
        when = datetime.fromisoformat(ev["start"]["dateTime"].replace("Z", "+00:00")).astimezone()
        meeting = find_meeting(ev)
        if not meeting:
            verdict = "no video link"
        elif meeting[0] == "teams":
            verdict = "Teams - 1-minute reminder only"
        elif meeting[0] == "meet":
            verdict = "Meet - will alert via waiting screen" if screen else "Meet - needs --meet-login"
        else:
            verdict = ("Zoom - 1-minute reminder, plus join alert if hosted on your Zoom account" if cfg.get("zoom")
                       else "Zoom - 1-minute reminder only")
        print(f"  {when:%H:%M}  {ev.get('summary') or '(untitled)'}")
        print(f"         {verdict}")
    if not events:
        print("  Nothing found. If you expected meetings, check calendar_ids in config.json.")


def peek(cfg: dict, url: str) -> None:
    screen = meet_waiting_screen.WaitingScreen(HERE / cfg["meet_profile_dir"])
    if not screen.signed_in:
        raise SystemExit("Not signed in - run --meet-login first.")
    try:
        r = screen.read("peek", url)
        deadline = time.time() + meet_waiting_screen.LOAD_GRACE_SECONDS + 5
        while r is None or (r.status == "no_info" and time.time() < deadline):
            time.sleep(3)
            r = screen.read("peek", url)
        shot = HERE / "meet_peek.png"
        screen.screenshot("peek", shot)
        print(f"Reading: {r}\nScreenshot: {shot}\n\nPage text:\n{screen.text('peek')[:800]}")
    finally:
        screen.shutdown()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--auth", action="store_true", help="run Google sign-in and exit")
    ap.add_argument("--once", action="store_true", help="poll once with debug logging and exit")
    ap.add_argument("--test-notify", action="store_true", help="send a test notification and exit")
    ap.add_argument("--tomorrow", action="store_true", help="list tomorrow's meetings and whether each can be watched")
    ap.add_argument("--meet-login", action="store_true", help="sign in to Google in the waiting-screen browser")
    ap.add_argument("--meet-peek", metavar="URL", help="show what the Meet waiting screen reports for one meeting")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.once else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    cfg = load_config()

    if args.test_notify:
        notify("Alex Example has joined", "Test meeting", "https://meet.google.com", cfg)
        return

    if args.meet_login:
        meet_waiting_screen.login(HERE / cfg["meet_profile_dir"])
        return

    if args.meet_peek:
        peek(cfg, args.meet_peek)
        return

    gs = google_session(cfg, interactive=args.auth)
    if args.auth:
        print(f"Signed in. Token saved to {TOKEN_PATH}")
        return

    if args.tomorrow:
        list_tomorrow(gs, cfg)
        return

    watcher = Watcher(cfg, gs)
    if args.once:
        events = current_events(gs, cfg)
        for ev in events:
            print(f"- {ev.get('summary')!r}: {find_meeting(ev)}")
        if not events:
            print("No meetings in the current window.")
        watcher.tick()
        return

    log.info("Watching calendars %s every %ss", cfg["calendar_ids"], cfg["poll_seconds"])
    last = time.time()
    while True:
        gap = time.time() - last
        if gap > cfg["poll_seconds"] * 4:
            log.warning("Last poll was %.0fs ago (sleep or throttling?)", gap)
        last = time.time()
        try:
            watcher.tick()
        except Exception as e:
            brief = transient_error(e)
            if brief:
                log.warning("poll skipped: %s (will retry)", brief)
            else:
                log.exception("poll failed")
        time.sleep(cfg["poll_seconds"])


if __name__ == "__main__":
    main()
