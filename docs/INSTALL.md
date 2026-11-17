# Installing meeting-join-alert

This guide takes a new user from nothing to a running watcher. Allow about 15 minutes for the basic
setup (steps 1–5). Step 6 is needed for Meet alerts; step 7 is optional.

You need:

- A Mac (the alerts use macOS notifications and `launchd`).
- Python 3.10 or newer (`brew install python` if `python3 --version` is older).
- A Google account whose calendar holds your meetings (Google Workspace or personal).
- Google Chrome, to read Meet waiting screens (step 6).
- Optional: Zoom admin rights, to create a Zoom app (step 7).

Which steps you need depends on what you want alerts for:

| You want… | Do steps |
| --- | --- |
| "Starts in 1 minute" pop-ups for Zoom and Teams | 1–5 |
| Who-joined alerts for **any** Meet, including external ones | 1–6 |
| Who-joined alerts for Zoom meetings hosted on **your** Zoom account | 1–5 and 7 |

---

## 1. Get the code

Put the folder anywhere in your home directory, for example `~/meeting-join-alert`. Copy only the
code and docs, **not** someone else's secrets (see [Sharing this folder](#sharing-this-folder)).

```sh
cd ~/meeting-join-alert
```

## 2. Run the installer

```sh
./install.sh --no-start
```

This:

1. creates a Python virtualenv in `.venv` and installs `requirements.txt`,
2. copies `config.example.json` to `config.json` if you don't have one yet,
3. writes a `launchd` service file to `~/Library/LaunchAgents/com.<your-username>.meeting-join-alert.plist`
   that points at this folder.

`--no-start` stops it before starting the service, because you haven't signed in to Google yet.

Optional but recommended:

```sh
brew install terminal-notifier   # lets a click on the banner open the meeting
```

## 3. Create a Google OAuth client

The script reads your calendar as you, using a Google Cloud OAuth client.
You do this once. If your company already has a client for this tool, ask for its
`client_secret.json` instead and skip to step 4.

1. Open <https://console.cloud.google.com> and create a project, or reuse one.
2. **APIs & Services → Library**: enable **Google Calendar API**.
3. **APIs & Services → OAuth consent screen**:
   - User type **Internal** (on Workspace). On a personal account choose *External* and add yourself as a test user.
   - Add the scope `.../auth/calendar.readonly`.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type **Desktop app**.
   - Download the JSON and save it as `client_secret.json` in this folder.

## 4. Edit `config.json`

At minimum:

```json
"my_names": ["Your Name"],
"zoom": null
```

`my_names` is how you appear in Meet and Zoom. It's used to stop alerting once you've joined.
Set `"zoom": null` unless you are doing step 7. Leave the placeholder values in and you'll get errors.

Every setting is explained in [CONFIGURATION.md](CONFIGURATION.md).

## 5. Sign in, test, start

```sh
.venv/bin/python meeting_join_alert.py --test-notify   # a test alert; allow notifications if macOS asks
.venv/bin/python meeting_join_alert.py --auth          # browser opens; sign in with your Google account
.venv/bin/python meeting_join_alert.py --tomorrow      # lists tomorrow's meetings and what each will get
.venv/bin/python meeting_join_alert.py --once          # one check of meetings starting soon, with debug output
./install.sh                                           # starts the background service
tail -f watcher.log                                    # watch it work
```

The `--auth` sign-in saves `google_token.json`, which refreshes itself. You won't need to sign in again
unless you revoke access or change scopes.

If you don't see the test alert:

- **System Settings → Notifications**: allow notifications for *terminal-notifier* or *Script Editor*
  (the fallback shows up as Script Editor).
- Check Focus / Do Not Disturb.

That's the basic install. The watcher starts at login and restarts itself if it crashes.

---

## 6. Meet: sign in the waiting-screen browser

To see who is in a Meet (yours, colleagues' or external), the script opens the meeting's pre-join screen in a hidden Chrome and read the
"Alex and 2 others are in this call" line. It never joins, and camera/mic are denied.

Needs Google Chrome in `/Applications`.

```sh
.venv/bin/python meeting_join_alert.py --meet-login
```

A separate Chrome window opens. Sign in to Google, open <https://meet.google.com> once to check, then
**quit that Chrome with Cmd-Q**. Then check it can read a meeting:

```sh
.venv/bin/python meeting_join_alert.py --meet-peek https://meet.google.com/abc-defg-hij
```

Then restart the service (`./install.sh`). Without this step Meet meetings can't be watched.

> **Security:** the sign-in is stored in `meet_profile/` with **unencrypted** cookies. Treat that
> folder like a password, and delete it to sign out.

## 7. Optional: Zoom

Only meetings hosted on **your** Zoom account can be seen. Other people's Zoom meetings still get the
1-minute reminder.

1. <https://marketplace.zoom.us> → **Develop → Build App → Server-to-Server OAuth** (needs a Zoom admin role).
2. Scopes: `meeting:read:meeting:admin`. For participant names add
   `dashboard:read:list_meeting_participants:admin` (Business plan or higher). Without it you get a
   single "Zoom meeting started" alert, which needs *Join before host* turned on for the meeting.
3. Activate the app, then copy the **Account ID**, **Client ID** and **Client Secret** into the
   `zoom` block of `config.json`.
4. Restart: `./install.sh`.

---

## Day-to-day commands

| Task | Command |
| --- | --- |
| Restart after changing config or code | `./install.sh` |
| Stop it | `launchctl bootout gui/$(id -u)/com.$(whoami).meeting-join-alert` |
| Uninstall the service | `./install.sh --uninstall` |
| See what's happening | `tail -f watcher.log` |
| Is it running? | `launchctl print gui/$(id -u)/com.$(whoami).meeting-join-alert \| grep state` |
| Preview tomorrow | `.venv/bin/python meeting_join_alert.py --tomorrow` |

## Updating

Replace `meeting_join_alert.py`, `meet_waiting_screen.py` and `requirements.txt` with the new
versions, then run `./install.sh` (it reinstalls packages and restarts the service). Your
`config.json`, tokens and `meet_profile/` are left alone. New settings get defaults, so an old
`config.json` keeps working.

## Sharing this folder

These files are **personal secrets**. Never copy them to someone else or commit them:

| File | What it is |
| --- | --- |
| `google_token.json` | Your Google sign-in (calendar access) |
| `meet_profile/` | Signed-in Chrome profile with unencrypted cookies (step 6) |
| `config.json` | May hold your Zoom client secret |
| `client_secret.json` | Your OAuth client; shareable inside your company but not publicly |
| `alerted.json`, `watcher.log` | Your meeting titles and history |

The `.gitignore` in this folder already excludes them. To hand the tool to a colleague, give them the
`.py` files, `requirements.txt`, `install.sh`, `config.example.json`, `README.md` and `docs/`.
