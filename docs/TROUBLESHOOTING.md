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
| `Google Calendar sign-in has expired - no meeting alerts of any kind until you sign in again` | Click **Sign in** on the alert, or run `.venv/bin/python meeting_join_alert.py --auth`. No restart needed. See [INSTALL.md](INSTALL.md#staying-signed-in). If this happens every 7 days, your OAuth app is in *Testing*: publish it (INSTALL step 3). |
| `Google Calendar sign-in is missing` | No `google_token.json` yet. Same fix. |
| `Google Calendar sign-in didn't complete: …` | The browser sign-in was cancelled or timed out (10 minutes). You'll be asked again on the next poll. |
| `Google sign-in missing or expired - run … --auth` (from `--once` / `--tomorrow`) | Same fix; those commands need a working sign-in. |
| `poll skipped: network unavailable…` / `timed out…` / `503…` | A temporary network or server problem. It retries on the next poll; ignore unless it keeps happening. |
| `Meet waiting-screen sign-in is missing` / `has expired` | Click **Sign in** on the alert (or run `--meet-login`), sign in in the Chrome window, then Cmd-Q it. Meetings that are still on get watched once you're back. |
| `Waiting screen for '…' doesn't show who's in the call (yet). Page says: …` | Usually just means nobody is there yet; it keeps watching. If it happens for meetings you know are busy, Google may have changed the page. Run `--meet-peek <url>` and compare the text with the patterns at the top of `meet_waiting_screen.py`. |
| `Can't watch '…' (meet): Meet says 'you can't join this video call'` | The signed-in account isn't allowed into that meeting (restricted to an org, or you weren't invited with that account). |
| `Can't watch '…' (zoom): not a meeting on your Zoom account` | Expected for other people's Zoom meetings. You still get the 1-minute reminder. |
| `Can't watch '…' (zoom): no Zoom credentials in config` | Expected if `zoom` is `null`. You still get the 1-minute reminder. |
| `Zoom Dashboard API unavailable (403)` | Your Zoom plan or app scopes don't include live participants. You'll get "Zoom meeting started" instead of names. |
| `Can't watch '…' (teams): no Teams API - start reminder only` | Expected for Teams. |
| `Ignoring push target N: …` | That entry in `push` has an unknown `service` or a missing `topic` / `server` / `token`. The others still work. |
| `Phone push to … failed: 401 Unauthorized …` / `403 Forbidden` | Wrong token. For Gotify, use an *application* token, not a client token. For ntfy, the topic is protected: check `token` or `user`/`password`. |
| `Phone push to … failed: network unavailable…` / `timed out…` | The push server couldn't be reached. The Mac alert still appeared. Check the `server` URL. |
| `Phone push skipped: Mac in use (idle …)` | Expected with `push_only_when_idle_seconds`: you were using the Mac. |

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

**Phone notifications don't arrive.** Run `--test-push`: it prints `OK` or the error for each
target. If it says `OK` but nothing shows up: for ntfy, check the app is subscribed to exactly that
topic on the same server; for Gotify, check the app is logged in to the server and that Android isn't
battery-optimising it. Phone Focus / Do Not Disturb modes can also hold them back.

**The Sign in alert says `client_secret.json is missing`.** Put the OAuth client file back in this
folder (INSTALL step 3), then click Sign in on the next alert or run `--auth`.

**Gotify on iPhone.** Gotify has no official iOS app. Use ntfy on iPhone.

**`watcher.log` is huge.** It's never rotated. It's safe to empty it: `: > watcher.log`.

**After a macOS or Python upgrade it won't start.** The virtualenv may point at the old Python.
Delete `.venv` and run `./install.sh`.
