# Architecture

meeting-join-alert is a single long-running Python process on your Mac. Every 30 seconds it reads your
Google Calendar, works out which video meetings start soon, and finds out (where it can) whether
anyone is already in them. When someone is, or when a Zoom/Teams meeting is about to start, it pops
up an alert.

There is no server, database or UI. State lives in a few small files next to the code.

## Components

```
                        launchd (com.<user>.meeting-join-alert)
                                     │ starts at login, restarts on crash
                                     ▼
┌────────────────────────── meeting_join_alert.py ──────────────────────────┐
│                                                                            │
│  main()  ──►  Watcher.tick()  every poll_seconds                           │
│                    │                                                       │
│                    ├─ current_events()  ──────────────►  Google Calendar API│
│                    │                                                       │
│                    ├─ find_meeting(ev) → ("meet"|"zoom"|"teams", id, url)  │
│                    │                                                       │
│                    ├─ remind()        Zoom/Teams: "starts in 1 minute"     │
│                    │                                                       │
│                    └─ check()                                              │
│                         ├─ meet ─► check_waiting_screen()                  │
│                         │    └─► meet_waiting_screen.py (headless Chrome)  │
│                         ├─ zoom ─► Zoom class ──────►  Zoom API            │
│                         └─ teams ─► (nothing to ask; reminder only)        │
│                                                                            │
│  announce() / notify()  ─►  show_banner()  terminal-notifier / osascript   │
│                          └►  show_alert()   osascript "display alert"      │
└────────────────────────────────────────────────────────────────────────────┘
```

| File | Role |
| --- | --- |
| `meeting_join_alert.py` | Everything except the waiting screen: config, auth, calendar, Meet and Zoom APIs, the poll loop, notifications, CLI. |
| `meet_waiting_screen.py` | Drives a headless Chrome (via Playwright) that keeps one tab per watched Meet open on the pre-join page and parses its text. |
| `install.sh` | Creates the virtualenv, `config.json` and the launchd plist; starts/stops the service. |
| `config.json` | User settings, merged over `DEFAULTS` in the script. See [CONFIGURATION.md](CONFIGURATION.md). |

## The poll loop

`main()` runs `Watcher.tick()` every `poll_seconds` (default 30). A failing tick is logged and the
loop carries on; network blips and Google/Zoom 5xx/429 errors are logged as one-line warnings
(`transient_error()`), anything else with a full traceback. If the gap between ticks is much longer
than expected (the Mac slept) it logs a warning. Sign-in problems never stop the loop: see
[Sign-ins](#sign-ins).

Each tick:

1. **Find meetings.** `current_events()` asks the Calendar API for timed events overlapping
   *now → now + `minutes_before_start`*, across every calendar in `calendar_ids`. Cancelled events,
   all-day events and ones you declined are dropped.
2. **Identify the platform.** `find_meeting()` looks first at the event's structured
   `conferenceData` (a native Google Meet), then searches the conference entry points, location and
   description for a Meet code, a Zoom meeting ID, or a Teams join link. Events with no video link are
   ignored.
3. **Track state.** Each meeting gets a key `"<event id>|<kind>|<meeting id>"` and an entry in
   `Watcher.state`. When an event leaves the window (it ended), its state is forgotten and any
   waiting-screen tab is closed.
4. **Start reminder (Zoom and Teams).** `remind()` fires once when the meeting is within
   `reminder_seconds_before` of its start, and is skipped if the watcher first sees the meeting more
   than 2 minutes after it started. Because the loop polls every 30 s, the alert lands 30–60 s before
   the start with the defaults.
5. **Check who's in.** `check()` asks the right source (below). As soon as anyone other than you is
   present, `announce()` sends **one** alert and marks the meeting done. If you are already in
   (your name from `my_names` is in the list, or Meet says you're in on another device), the meeting
   is marked done with no alert. If the source can't see the meeting at all, it raises `NotAvailable`;
   that's logged once and the meeting is marked done.

### Meeting lifecycle

```
            enters window                      someone else joins
  (unseen) ───────────────► watching ─────────────────────────────► alerted (done)
                               │  │
                               │  └── you join / can't be watched ──► done (no alert)
                               │
                               └── event ends ──► forgotten
```

For Zoom/Teams the 1-minute reminder runs alongside this, with its own key (`…|reminder`), so it
still fires for meetings that are "done" because they can't be watched.

## How each platform is checked

### Google Meet

Every Meet is checked by reading its pre-join waiting screen (below). The Meet REST API isn't used.

### The Meet waiting screen (`meet_waiting_screen.py`)

`WaitingScreen` launches the installed Google Chrome headless through Playwright, using its own
profile directory (`meet_profile/`) that you signed into with `--meet-login`. For each watched Meet it
opens a tab on the meeting URL and leaves it open; each tick re-reads the page text. `parse()`
recognises:

| Status | Page shows | Watcher does |
| --- | --- | --- |
| `ok` | "Alex and 2 others are in this call" | Alert with names |
| `empty` | "No one else is here" | Keep watching |
| `me_elsewhere` | "You're in this call on another device" | Done, no alert |
| `blocked` | "You can't join this video call", meeting ended… | Log and stop watching |
| `signed_out` | Redirected to accounts.google.com | `MeetSignIn.signed_out()`: pause and ask to sign in ([Sign-ins](#sign-ins)) |
| `no_info` | Nothing recognisable after 45 s | Log once, keep watching |

Chrome only runs while at least one tab is open; it's shut down when the last watched Meet ends.
The profile is launched with `--use-mock-keychain` both at login and in headless mode, because
otherwise the headless browser can't decrypt the cookies saved by the login window. This is why the
cookies are stored unencrypted.

This approach depends on Meet's English page text (`--lang=en-GB` is forced). If Google changes the
wording, update the marker lists and regexes at the top of `meet_waiting_screen.py`; `--meet-peek URL`
prints the page text and saves `meet_peek.png` to help.

### Zoom

`Zoom` uses a Server-to-Server OAuth app (tokens are cached until a minute before expiry).

- `GET /meetings/{id}` gives the status (`waiting` / `started`). A 400/404 means the meeting isn't
  on your account → `NotAvailable`.
- `GET /metrics/meetings/{id}/participants?type=live` (Dashboard API, Business plan and up) gives
  names. If that returns 400/401/403 once, it's switched off for the session and the watcher falls
  back to a single "Zoom meeting started" alert.

Every Zoom meeting also gets the 1-minute start reminder, whatever the API can see.

### Microsoft Teams

There's no practical API to see who is in someone else's Teams meeting, so Teams meetings only get
the 1-minute start reminder, with a Join button that opens the Teams link from the invite.

## Notifications

`notify()` sends the alert in the style set by `style`:

- **banner**: `terminal-notifier` if installed (a click opens the meeting), else
  `osascript display notification` (shown as coming from Script Editor; clicking does nothing).
- **alert**: `osascript display alert`, a large centred window with **Join** / **Dismiss**. It runs as
  a background process so the poll loop doesn't wait for you, and closes itself after
  `alert_timeout_seconds`.

The alert sound comes from `/System/Library/Sounds/<sound>.aiff`.

### Phone notifications

If `push` has targets, `notify()` also starts `push_if_away()` in a daemon thread, so a slow or
unreachable push server never delays polling or the Mac alert. One-shot commands (`--once`) call
`wait_for_pushes()` before exiting so the thread isn't cut off.

- `push_if_away()` checks `push_only_when_idle_seconds` against the Mac's input idle time
  (`HIDIdleTime` from `ioreg -c IOHIDSystem`), then calls `send_push()`.
- `send_push()` posts to each target with a 10-second timeout, logs a one-line result per target, and
  never raises.
- **ntfy:** JSON published to the server root (`{"topic", "title", "message", "priority", "click",
  "actions"}`), not the `Title:`/`Click:` headers, because HTTP headers can't carry non-ASCII names.
- **Gotify:** `POST <server>/message` with the token in `X-Gotify-Key` (never in the URL, so it can't
  reach logs). `extras.client::notification.click.url` makes a tap open the meeting.
- `valid_push_targets()` runs at config load and drops unusable entries with a warning.
- Log lines name a target by `push_label()`: the Gotify host, or the first 6 characters of the ntfy
  topic, since on ntfy.sh the topic works like a password.

## Sign-ins

Two sign-ins can expire: calendar access and the waiting-screen Chrome profile. Each is a `SignIn`
subclass with the same behaviour: `pause()` logs one warning, sends one phone push, and shows a Mac
alert with **Sign in** / **Later** (repeated every 2 hours while still broken). `resume()` sends a
"working again" banner. The alert and the sign-in itself run in a thread, so polling carries on.

- **`CalendarSignIn`** owns the calendar session. Each tick, `session()` checks `google_token.json`'s
  mtime and reloads it when it changes. That makes the token file the hand-off: the **Sign in**
  button (`google_sign_in()`, browser OAuth with a 10-minute timeout) and `--auth` in a terminal both
  just write it, and the next poll resumes. A non-retryable `RefreshError`, at load or mid-poll,
  pauses. Network errors and retryable refresh errors propagate as normal transient errors, so a
  network blip isn't mistaken for being signed out. Tokens are written atomically (write, then
  rename) so a half-written file is never read.
- **`MeetSignIn`** watches the Chrome profile. When there are no cookies, or Meet redirects to
  accounts.google.com, it shuts the headless Chrome (freeing the profile) and pauses. Meet meetings
  stay pending rather than being marked done. **Sign in** opens the visible Chrome
  (`open_sign_in_window()`) and waits for it to quit; the next poll then resumes and re-opens tabs for
  meetings still in the window. Playwright is only touched from the poll thread.
- **Startup:** the service never exits for a missing or dead token; it starts paused. `--once` and
  `--tomorrow` still exit with a message, and `--auth` always runs a fresh sign-in.

## State and files on disk

| File | Written by | Purpose |
| --- | --- | --- |
| `google_token.json` | `--auth`, the **Sign in** button | Your OAuth refresh token (mode 600). The watcher reloads it when it changes. |
| `alerted.json` | `announce()`, `remind()` | Meeting keys already alerted on, with timestamps, so a restart doesn't repeat alerts. Entries older than 2 days are dropped on load. |
| `meet_profile/` | `--meet-login`, Chrome | Signed-in Chrome profile for waiting screens (mode 700). |
| `watcher.log` | launchd (stdout/stderr) | The log. It is never rotated; truncate it if it gets large. |
| `meet_peek.png` | `--meet-peek` | Screenshot for debugging the waiting screen. |

`Watcher.state` (in memory) holds per-meeting progress: `done`, `started` (Zoom), and flags that stop
repeated waiting-screen log lines.

## Security model

- Google API access is read-only: `calendar.readonly`.
- The waiting-screen Chrome profile is a full Google session with unencrypted cookies.
- Nothing is sent anywhere except Google, Zoom and (for alerts) macOS itself, unless you set `push`:
  then each alert's title, meeting title, attendee names and meeting link go to your ntfy or Gotify
  server. On public ntfy.sh, anyone who knows the topic name can read them.
- Push tokens and ntfy topics live in `config.json`, which is git-ignored.

## Extending it

- **A new video platform:** add a regex and a branch to `find_meeting()` returning a new `kind`, then
  either a branch in `Watcher.check()` that produces `(id, name)` pairs and calls `announce()`, or add
  the kind to the `remind()` call in `tick()` for start reminders only.
- **Another calendar:** add its ID (from Google Calendar settings) to `calendar_ids`.
- **Different alert behaviour:** everything goes through `notify()`, so that's the one place to
  change. For another push service, add a `push_<service>()` function, its required keys to
  `PUSH_REQUIRED`, and a branch in `send_push()`.
