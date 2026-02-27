#!/bin/bash
#
# Cron-safe Telemost processor entry point.
# Uses PID file to prevent concurrent runs.
#
# Crontab example (every 30 min):
#   */30 * * * * /path/to/telemost/scripts/process.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
ROOT_DIR="$(dirname "$SKILL_DIR")"

# Config path (override with YANDEX_TELEMOST_CONFIG env var)
CONFIG_PATH="${YANDEX_TELEMOST_CONFIG:-$ROOT_DIR/config.json}"

# PID file lock
PIDFILE="/tmp/telemost-process.pid"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Already running (PID $(cat "$PIDFILE")), skipping"
    exit 0
fi
echo $$ > "$PIDFILE"
trap "rm -f '$PIDFILE'" EXIT

# Verify config exists
if [ ! -f "$CONFIG_PATH" ]; then
    echo "Config not found: $CONFIG_PATH"
    echo "Set YANDEX_TELEMOST_CONFIG or place config.json in repository root."
    exit 1
fi

# Run processor
python3 "$SCRIPT_DIR/process_meeting.py" --config "$CONFIG_PATH" "$@"
