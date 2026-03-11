#!/bin/bash
# Cron-safe wrapper for form export with PID lock

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK_FILE="/tmp/yandex-forms-export.lock"
PID=$$

# Cleanup on exit
cleanup() {
    rm -f "$LOCK_FILE"
}
trap cleanup EXIT

# Check for existing lock
if [[ -f "$LOCK_FILE" ]]; then
    OLD_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Another export is running (PID: $OLD_PID)" >&2
        exit 1
    fi
fi

# Write our PID
echo "$PID" > "$LOCK_FILE"

# Run export with all passed arguments
exec python "${SCRIPT_DIR}/export_responses.py" "$@"
