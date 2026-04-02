#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

pytest -q \
  common/tests/test_config_auth.py \
  common/tests/test_oauth_setup.py \
  common/tests/test_docs.py \
  mail/scripts/test_fetch_emails.py \
  forms/scripts/test_discover_forms.py \
  tracker/scripts/test_tracker_client.py \
  disk/scripts/test_download.py \
  telemost/scripts/test_conference.py \
  telemost/scripts/test_settings.py \
  telemost/scripts/test_telemost.py \
  calendar/scripts/test_create_event.py
