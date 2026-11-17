# Troubleshooting

Start with the log: `tail -50 watcher.log`. For a detailed look at what's happening right now, run
one check with debug output:

```sh
.venv/bin/python meeting_join_alert.py --once
```

And to see what each of tomorrow's meetings will get:

```sh
.venv/bin/python meeting_join_alert.py --tomorrow
```

## No alerts at all

| Check | How |
| --- | --- |
| Is the service running? | `launchctl print gui/$(id -u)/com.$(whoami).meeting-join-alert \| grep state` should say `running`. If not, run `./install.sh`. |
| Can it post notifications? | `.venv/bin/python meeting_join_alert.py --test-notify`. If nothing appears, allow notifications for *terminal-notifier* or *Script Editor* in System Settings → Notifications, and check Focus / Do Not Disturb. |
| Is it seeing your meetings? | `--tomorrow` or `--once`. If calendars look empty, check `calendar_ids`. |
| Was the Mac asleep? | The log says `Last poll was …s ago (sleep or throttling?)`. Nothing runs while the Mac sleeps. |

## Log messages

| Message | Meaning / fix |
| --- | --- |
| `No valid Google token - run --auth` | Run `.venv/bin/python meeting_join_alert.py --auth` in a terminal, then `./install.sh`. |
| `invalid_grant` / `RefreshError` at start-up | Your Google sign-in was revoked or expired. Delete `google_token.json` and run `--auth` again. Needs `client_secret.json`. |
| `poll skipped: network unavailable…` / `timed out…` / `503…` | A temporary network or server problem. It retries on the next poll; ignore unless it keeps happening. |
| `The Meet browser isn't signed in` / `waiting screen not set up` | Run `--meet-login`, sign in, Cmd-Q that Chrome, then `./install.sh`. |
| `Can't watch '…': the Meet browser is signed out` | The waiting-screen session expired. Run `--meet-login` again. |
| `Waiting screen for '…' doesn't show who's in the call (yet). Page says: …` | Usually just means nobody is there yet; it keeps watching. If it happens for meetings you know are busy, Google may have changed the page. Run `--meet-peek <url>` and compare the text with the patterns at the top of `meet_waiting_screen.py`. |
| `Can't watch '…' (meet): Meet says 'you can't join this video call'` | The signed-in account isn't allowed into that meeting (restricted to an org, or you weren't invited with that account). |
| `Can't watch '…' (zoom): not a meeting on your Zoom account` | Expected for other people's Zoom meetings. You still get the 1-minute reminder. |
| `Can't watch '…' (zoom): no Zoom credentials in config` | Expected if `zoom` is `null`. You still get the 1-minute reminder. |
| `Zoom Dashboard API unavailable (403)` | Your Zoom plan or app scopes don't include live participants. You'll get "Zoom meeting started" instead of names. |
| `Can't watch '…' (teams): no Teams API - start reminder only` | Expected for Teams. |

## Specific problems

**I got alerted although I was already in the meeting.** Your name in the meeting doesn't exactly
match anything in `my_names`. Check the name shown in the alert and add that spelling.

**I never get alerted for a meeting I joined late on another device.** Working as intended: once
you're seen in the meeting, it stops.

**The start reminder didn't fire.** It only fires for events whose invite contains a Zoom or Teams
link, and only if the watcher sees the meeting before it is 2 minutes old. Check `--tomorrow` lists it
as "1-minute reminder", that `reminder_seconds_before` isn't `0`, and that `minutes_before_start`
is at least 1.

**I want an alert again for a meeting that already alerted.** Delete its line from `alerted.json`
(or the whole file) and restart.

**Clicking the banner does nothing.** Install `terminal-notifier` (`brew install terminal-notifier`);
the built-in fallback can't open links. The big centred alert's Join button works either way.

**Headless Chrome uses CPU / I see a Chrome process.** It only runs while a Meet is being watched via
the waiting screen, and quits when the last one ends.

**`watcher.log` is huge.** It's never rotated. It's safe to empty it: `: > watcher.log`.

**After a macOS or Python upgrade it won't start.** The virtualenv may point at the old Python.
Delete `.venv` and run `./install.sh`.
