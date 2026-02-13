#!/bin/bash
#
# Cron-safe email fetcher entry point.
# Uses PID file to prevent concurrent runs.
#
# Crontab example (every 15 min):
#   */15 * * * * /path/to/yandex-mail/scripts/fetch.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"

# Data directory (override with YANDEX_MAIL_DATA env var)
DATA_DIR="${YANDEX_MAIL_DATA:-$(dirname "$(dirname "$SKILL_DIR")")/email-handler}"
CONFIG_PATH="$DATA_DIR/config.json"

# PID file lock
PIDFILE="/tmp/yandex-mail-fetch.pid"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Already running (PID $(cat "$PIDFILE")), skipping"
    exit 0
fi
echo $$ > "$PIDFILE"
trap "rm -f '$PIDFILE'" EXIT

# Verify config exists
if [ ! -f "$CONFIG_PATH" ]; then
    echo "Config not found: $CONFIG_PATH"
    echo "Copy config.example.json to $CONFIG_PATH and configure."
    exit 1
fi

# Run fetcher
cd "$DATA_DIR"
python3 "$SCRIPT_DIR/fetch_emails.py" --config "$CONFIG_PATH" "$@"
