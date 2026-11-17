#!/usr/bin/env bash
# Install meeting-join-alert for the current macOS user.
#
#   ./install.sh            set up Python, config and the background service, then start it
#   ./install.sh --no-start set everything up but don't load the background service
#   ./install.sh --uninstall stop and remove the background service (leaves this folder alone)
#
# Safe to run again: it only creates what's missing and reloads the service.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.$(whoami).meeting-join-alert"
PLIST="${MJA_PLIST_PATH:-$HOME/Library/LaunchAgents/$LABEL.plist}"
DOMAIN="gui/$(id -u)"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!!  %s\033[0m\n' "$*"; }

if [[ "${1:-}" == "--uninstall" ]]; then
  say "Stopping and removing $LABEL"
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  say "Done. Delete $DIR yourself if you want to remove everything (it holds your tokens)."
  exit 0
fi

[[ "$(uname)" == "Darwin" ]] || { echo "This tool only runs on macOS."; exit 1; }

# ---- Python
# macOS's own python3 is often 3.9, so look for a newer one (e.g. from Homebrew) first.
PY=""
for cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  p="$(command -v "$cand" || true)"
  if [[ -n "$p" ]] && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then PY="$p"; break; fi
done
if [[ -x "$DIR/.venv/bin/python" ]] && ! "$DIR/.venv/bin/python" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
  warn "Existing .venv is broken or too old - recreating it"
  rm -rf "$DIR/.venv"
fi
if [[ ! -x "$DIR/.venv/bin/python" ]]; then
  [[ -n "$PY" ]] || { echo "Python 3.10+ not found. Install it with: brew install python"; exit 1; }
  say "Creating virtualenv in .venv"
  "$PY" -m venv "$DIR/.venv"
fi
say "Installing Python packages"
"$DIR/.venv/bin/pip" install --quiet --upgrade pip
"$DIR/.venv/bin/pip" install --quiet -r "$DIR/requirements.txt"

# ---- optional extras
command -v terminal-notifier >/dev/null || warn "Optional: 'brew install terminal-notifier' makes clicking a banner open the meeting."
[[ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]] \
  || warn "Google Chrome not found in /Applications. Needed to watch Google Meet meetings."

# ---- config
if [[ ! -f "$DIR/config.json" ]]; then
  say "Creating config.json from config.example.json"
  cp "$DIR/config.example.json" "$DIR/config.json"
  warn "Edit config.json: set my_names to your name as it appears in Meet/Zoom, and set zoom to null if you have no Zoom app."
fi
[[ -f "$DIR/client_secret.json" || -f "$DIR/google_token.json" ]] \
  || warn "No client_secret.json yet. Follow docs/INSTALL.md step 3 to create it, then run: .venv/bin/python meeting_join_alert.py --auth"

# ---- launchd service
say "Writing $PLIST"
mkdir -p "$(dirname "$PLIST")"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$DIR/.venv/bin/python</string>
        <string>$DIR/meeting_join_alert.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>ProcessType</key>
    <string>Interactive</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>60</integer>
    <key>StandardOutPath</key>
    <string>$DIR/watcher.log</string>
    <key>StandardErrorPath</key>
    <string>$DIR/watcher.log</string>
</dict>
</plist>
EOF

if [[ "${1:-}" == "--no-start" ]]; then
  say "Not starting. Start later with: launchctl bootstrap $DOMAIN $PLIST"
  exit 0
fi

if [[ ! -f "$DIR/google_token.json" ]]; then
  warn "Not starting the service yet: sign in to Google first with"
  warn "  $DIR/.venv/bin/python $DIR/meeting_join_alert.py --auth"
  warn "then run ./install.sh again."
  exit 0
fi

say "(Re)starting $LABEL"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
say "Running. Follow the log with: tail -f $DIR/watcher.log"
