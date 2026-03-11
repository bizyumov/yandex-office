#!/usr/bin/env python3
"""Manage Yandex Telemost conferences."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from telemost.lib.client import TelemostError, YandexTelemostClient


def _parse_csv(value: str | None, *, allow_clear: bool = False) -> list[str] | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return [] if allow_clear else None
    return [item.strip() for item in stripped.split(",") if item.strip()]


def _build_live_stream(args: argparse.Namespace) -> dict[str, str] | None:
    if not any(
        [
            args.live_stream_access_level,
            args.live_stream_title,
            args.live_stream_description,
        ]
    ):
        return None
    payload = {
        "access_level": args.live_stream_access_level or "PUBLIC",
    }
    if args.live_stream_title is not None:
        payload["title"] = args.live_stream_title
    if args.live_stream_description is not None:
        payload["description"] = args.live_stream_description
    return payload


def _add_shared_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account", "-a", required=True, help="Account name")


def _add_conference_options(parser: argparse.ArgumentParser, *, include_defaults: bool) -> None:
    parser.add_argument(
        "--access-level",
        default="PUBLIC" if include_defaults else None,
        help="Conference access level (PUBLIC or ORGANIZATION)",
    )
    parser.add_argument(
        "--waiting-room",
        default="PUBLIC" if include_defaults else None,
        help="Waiting room level (PUBLIC, ORGANIZATION, ADMINS)",
    )
    parser.add_argument(
        "--cohosts",
        help=(
            "Comma-separated cohost emails"
            + ("" if include_defaults else "; pass empty string to clear cohosts")
        ),
    )
    parser.add_argument(
        "--live-stream-access-level",
        help="Live stream access level (PUBLIC or ORGANIZATION)",
    )
    parser.add_argument("--live-stream-title", help="Live stream title")
    parser.add_argument("--live-stream-description", help="Live stream description")


def _result(payload: dict, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Yandex Telemost conferences")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Create a conference")
    _add_shared_options(create_parser)
    _add_conference_options(create_parser, include_defaults=True)

    get_parser = subparsers.add_parser("get", help="Read conference info")
    _add_shared_options(get_parser)
    get_parser.add_argument("--id", required=True, help="Conference ID")

    update_parser = subparsers.add_parser("update", help="Update conference settings")
    _add_shared_options(update_parser)
    update_parser.add_argument("--id", required=True, help="Conference ID")
    _add_conference_options(update_parser, include_defaults=False)

    args = parser.parse_args()

    try:
        client = YandexTelemostClient(account=args.account)
        if args.command == "create":
            payload = client.create_conference(
                access_level=args.access_level,
                waiting_room_level=args.waiting_room,
                cohosts=_parse_csv(args.cohosts) or [],
                live_stream=_build_live_stream(args),
            )
            return _result(payload)
        if args.command == "get":
            return _result(client.get_conference(args.id))
        payload = client.update_conference(
            args.id,
            access_level=args.access_level,
            waiting_room_level=args.waiting_room,
            cohosts=_parse_csv(args.cohosts, allow_clear=True) if args.cohosts is not None else None,
            live_stream=_build_live_stream(args),
        )
        return _result(payload)
    except (TelemostError, ValueError) as exc:
        payload = exc.to_dict() if isinstance(exc, TelemostError) else {"error": str(exc)}
        return _result(payload, exit_code=1)


if __name__ == "__main__":
    sys.exit(main())
