#!/bin/bash
#
# Cron-safe email fetcher entry point.
# Uses PID file to prevent concurrent runs.
#
# Crontab example (every 15 min):
#   */15 * * * * /path/to/mail/scripts/fetch.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE_DIR="${OPENCLAW_AGENT_DIR:-$(pwd)}"
DATA_DIR="${YANDEX_MAIL_DATA:-$WORKSPACE_DIR/yandex-data}"
AGENT_CONFIG_PATH="$DATA_DIR/config.agent.json"

# PID file lock
PIDFILE="/tmp/mail-fetch.pid"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Already running (PID $(cat "$PIDFILE")), skipping"
    exit 0
fi
echo $$ > "$PIDFILE"
trap "rm -f '$PIDFILE'" EXIT

# Verify agent config exists
if [ ! -f "$AGENT_CONFIG_PATH" ]; then
    echo "Agent config not found: $AGENT_CONFIG_PATH"
    echo "Create yandex-data/config.agent.json in the workspace before running."
    exit 1
fi

# Run fetcher
cd "$WORKSPACE_DIR"
python3 "$SCRIPT_DIR/fetch_emails.py" "$@"
