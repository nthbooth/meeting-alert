# Configuration

Settings live in `config.json` next to the script. Anything you leave out takes the default shown
below, so a minimal file works. Use a different file by setting the environment variable
`MJA_CONFIG=/path/to/config.json`.

Restart the watcher after changing it: `./install.sh`.

## All settings

| Key | Default | What it does |
| --- | --- | --- |
| `my_names` | `[]` | Your display name(s) in Meet and Zoom, e.g. `["Alex Smith", "Alex"]`. Case-insensitive, exact match. Once one of these is in a meeting the watcher stops alerting for it. **Set this.** |
| `calendar_ids` | `["primary"]` | Google calendars to read. Add shared calendars by ID (Google Calendar → Settings → the calendar → *Calendar ID*). |
| `minutes_before_start` | `10` | How long before a meeting's start the watcher begins checking who's in it. Must be at least 1 for the start reminder to work. |
| `poll_seconds` | `30` | How often to check. Lower means faster alerts but more API calls. |
| `reminder_seconds_before` | `60` | Zoom and Teams meetings get a "starts in 1 minute" alert this many seconds before the start (it actually lands up to `poll_seconds` later). `0` turns the reminder off. |
| `style` | `"both"` | `"alert"`: large centred window with Join button. `"banner"`: normal notification. `"both"`: both. |
| `alert_timeout_seconds` | `300` | The centred alert closes itself after this many seconds. `0` = stays until you dismiss it. |
| `sound` | `"Glass"` | Any name from `/System/Library/Sounds` without `.aiff`: Basso, Blow, Bottle, Frog, Funk, Glass, Hero, Morse, Ping, Pop, Purr, Sosumi, Submarine, Tink. |
| `meet_profile_dir` | `"meet_profile"` | Folder for the Chrome profile used to read Meet waiting screens, relative to the script. Sign it in with `--meet-login` (see [INSTALL.md](INSTALL.md#6-meet-sign-in-the-waiting-screen-browser)). |
| `google_client_secret` | `"client_secret.json"` | OAuth client file, only needed for `--auth`. |
| `zoom` | `null` | `null` to skip Zoom's API, or `{"account_id": "...", "client_id": "...", "client_secret": "..."}` from a Zoom Server-to-Server OAuth app. Zoom and Teams meetings get the start reminder either way. |

## Examples

Minimal, no extras:

```json
{
  "my_names": ["Alex Smith"],
  "zoom": null
}
```

Quieter: banner only, no big window, reminder 2 minutes ahead:

```json
{
  "my_names": ["Alex Smith"],
  "style": "banner",
  "reminder_seconds_before": 120
}
```

Everything on:

```json
{
  "my_names": ["Alex Smith"],
  "calendar_ids": ["primary", "team-calendar@group.calendar.google.com"],
  "minutes_before_start": 10,
  "zoom": {
    "account_id": "abc123",
    "client_id": "def456",
    "client_secret": "keep-this-secret"
  }
}
```
