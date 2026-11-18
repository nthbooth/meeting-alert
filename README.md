# meeting-join-alert

A small macOS background tool that watches your Google Calendar and pops up an alert:

- **when someone joins a Google Meet or Zoom meeting before you have**, so you're not the one keeping
  people waiting, and
- **one minute before a Zoom or Teams meeting starts**, for meetings where there's no way to see
  who's in them.

It stops alerting for a meeting once you're in it, and alerts only once per meeting. It can also send
each alert to your phone via **ntfy** or **Gotify** (install step 8).

## Quick start

```sh
cd ~/meeting-join-alert
./install.sh --no-start                                   # Python env, config.json, launchd service
# create client_secret.json - see docs/INSTALL.md step 3
# edit config.json: set my_names, and "zoom": null
.venv/bin/python meeting_join_alert.py --test-notify      # allow notifications
.venv/bin/python meeting_join_alert.py --auth             # sign in to Google
./install.sh                                              # start it in the background
```

Full walkthrough: **[docs/INSTALL.md](docs/INSTALL.md)**.

## What it can see

| Meeting | Needs | You get |
| --- | --- | --- |
| Any Google Meet (yours, colleagues' or external) | Waiting screen (install step 6) | Names shown on the pre-join screen |
| Zoom hosted on your Zoom account, Business plan or higher | Zoom app (step 7) | Name of the first person to join, plus the 1-minute reminder |
| Zoom hosted on your Zoom account, Pro plan | Zoom app (step 7) | "Zoom meeting started", plus the 1-minute reminder |
| Any other Zoom | Basic install | "Zoom meeting starts in 1 minute" |
| Microsoft Teams | Basic install | "Teams meeting starts in 1 minute" |

Every alert has a **Join** button that opens the meeting link from the invite.

## Commands

```
meeting_join_alert.py                  run forever (what the background service runs)
meeting_join_alert.py --auth           one-off Google sign-in
meeting_join_alert.py --test-notify    show a test alert
meeting_join_alert.py --test-push      send a test phone notification (ntfy / Gotify)
meeting_join_alert.py --once           one check of meetings starting soon, with debug output
meeting_join_alert.py --tomorrow       list tomorrow's meetings and what each will get
meeting_join_alert.py --meet-login     sign in to Google in the waiting-screen Chrome
meeting_join_alert.py --meet-peek URL  show what the Meet waiting screen says for one meeting

./install.sh                           set up / update / restart the background service
./install.sh --uninstall               remove the background service
```

Run the Python commands with `.venv/bin/python` from this folder.

## Documentation

| Doc | For |
| --- | --- |
| [docs/INSTALL.md](docs/INSTALL.md) | Setting it up from scratch, optional extras, updating, what not to share |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every `config.json` setting |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it works: poll loop, per-platform checks, files, security, extending it |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Log messages and common problems |

## Files

| Path | What |
| --- | --- |
| `meeting_join_alert.py` | The watcher and CLI |
| `meet_waiting_screen.py` | Headless-Chrome reader for Meet pre-join screens |
| `install.sh` | Installer / service manager |
| `config.example.json` | Starting point for `config.json` |
| `requirements.txt` | Python packages |
| `config.json`, `google_token.json`, `client_secret.json`, `meet_profile/`, `alerted.json`, `watcher.log` | Your settings, secrets and state. **Don't share these** (see INSTALL.md). |

## Requirements

macOS, Python 3.10+, a Google account. Optional: Google Chrome (waiting screen),
`terminal-notifier` (clickable banners), a Zoom Server-to-Server OAuth app, the ntfy app or a Gotify
server (phone notifications).
