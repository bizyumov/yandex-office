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
WORKSPACE_DIR="${OPENCLAW_AGENT_DIR:-$(pwd)}"
DATA_DIR="$WORKSPACE_DIR/yandex-data"
AGENT_CONFIG_PATH="$DATA_DIR/config.agent.json"

# PID file lock
PIDFILE="/tmp/telemost-process.pid"

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

# Run processor
cd "$WORKSPACE_DIR"
python3 "$SCRIPT_DIR/process_meeting.py" "$@"
