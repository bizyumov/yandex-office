#!/usr/bin/env python3
"""Manage Yandex Telemost organization settings."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from telemost.lib.client import TelemostError, YandexTelemostClient


def _parse_roles(value: str | None) -> list[str] | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return []
    return [item.strip().upper() for item in stripped.split(",") if item.strip()]


def _emit(payload: dict, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Yandex Telemost organization settings")
    subparsers = parser.add_subparsers(dest="command", required=True)

    get_parser = subparsers.add_parser("get", help="Read organization settings")
    get_parser.add_argument("--account", "-a", required=True, help="Account name")
    get_parser.add_argument("--org-id", type=int, help="Organization ID; defaults to token file org_id")

    update_parser = subparsers.add_parser("update", help="Update organization settings")
    update_parser.add_argument("--account", "-a", required=True, help="Account name")
    update_parser.add_argument("--org-id", type=int, help="Organization ID; defaults to token file org_id")
    update_parser.add_argument("--settings-file", help="Path to JSON file with full OrganizationSettings payload")
    update_parser.add_argument("--waiting-room-adhoc", help="PUBLIC, ORGANIZATION, or ADMINS")
    update_parser.add_argument("--waiting-room-calendar", help="PUBLIC, ORGANIZATION, or ADMINS")
    update_parser.add_argument("--cloud-recording-email-receivers", help="Comma-separated roles")
    update_parser.add_argument("--summarization-email-receivers", help="Comma-separated roles")
    update_parser.add_argument("--cloud-recording-allowed-roles", help="Comma-separated roles")
    update_parser.add_argument("--summarization-allowed-roles", help="Comma-separated roles")

    args = parser.parse_args()

    try:
        client = YandexTelemostClient(account=args.account)
        if args.command == "get":
            return _emit(client.get_org_settings(org_id=args.org_id))

        file_payload = None
        if args.settings_file:
            file_payload = json.loads(Path(args.settings_file).read_text(encoding="utf-8"))

        payload = client.build_org_settings_payload(
            file_payload=file_payload,
            waiting_room_level_adhoc=args.waiting_room_adhoc,
            waiting_room_level_calendar=args.waiting_room_calendar,
            cloud_recording_email_receivers=_parse_roles(args.cloud_recording_email_receivers),
            summarization_email_receivers=_parse_roles(args.summarization_email_receivers),
            cloud_recording_allowed_roles=_parse_roles(args.cloud_recording_allowed_roles),
            summarization_allowed_roles=_parse_roles(args.summarization_allowed_roles),
        )
        return _emit(client.update_org_settings(payload, org_id=args.org_id))
    except (TelemostError, ValueError, json.JSONDecodeError, OSError) as exc:
        payload = exc.to_dict() if isinstance(exc, TelemostError) else {"error": str(exc)}
        return _emit(payload, exit_code=1)


if __name__ == "__main__":
    sys.exit(main())
