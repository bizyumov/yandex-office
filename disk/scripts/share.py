#!/usr/bin/env python3
"""Manage Yandex Disk publish/share settings."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from download import YandexDisk


def _csv_list(value: str | None) -> list[str] | None:
    if value is None:
        return None
    items = [item.strip() for item in value.split(",")]
    items = [item for item in items if item]
    return items or None


def _build_share_kwargs(args: argparse.Namespace) -> dict:
    return {
        "path": args.path,
        "access": args.access,
        "org_id": args.org_id,
        "rights": args.rights,
        "password": args.password,
        "available_until": args.available_until,
        "user_ids": _csv_list(args.user_ids),
        "group_ids": _csv_list(args.group_ids),
        "department_ids": _csv_list(args.department_ids),
    }


def add_common_auth(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--account", help="Account name for token resolution")
    subparser.add_argument("--token-file", help="Path to token JSON file ({account}.token)")
    subparser.add_argument("--auth-dir", default=None, help="Auth directory (default: from config)")


def add_path_arg(
    subparser: argparse.ArgumentParser,
    *,
    option: str = "--path",
    help_text: str = "Disk resource path (e.g. disk:/foo/bar.txt)",
) -> None:
    subparser.add_argument(option, required=True, help=help_text)


def add_share_options(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--access", choices=["employees", "all"], help="Access macro")
    subparser.add_argument(
        "--org-id",
        help="Organization ID for employees access; optional if stored as org_id in the token file",
    )
    subparser.add_argument(
        "--rights",
        choices=[
            "read",
            "write",
            "read_without_download",
            "read_with_password",
            "read_with_password_without_download",
        ],
        help="Share rights mode",
    )
    subparser.add_argument("--password", help="Password for protected share modes")
    subparser.add_argument(
        "--available-until",
        type=int,
        help="TTL in seconds; future Unix timestamps are also accepted for compatibility",
    )
    subparser.add_argument("--user-ids", help="Comma-separated user IDs")
    subparser.add_argument("--group-ids", help="Comma-separated group IDs")
    subparser.add_argument("--department-ids", help="Comma-separated department IDs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Yandex Disk share links")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    subparsers = parser.add_subparsers(dest="command", required=True)

    publish_parser = subparsers.add_parser("publish", help="Publish a resource and create share link")
    add_common_auth(publish_parser)
    add_path_arg(publish_parser)
    add_share_options(publish_parser)

    update_parser = subparsers.add_parser("update", help="Update existing share settings")
    add_common_auth(update_parser)
    add_path_arg(update_parser)
    add_share_options(update_parser)

    info_parser = subparsers.add_parser("info", help="Get current share info")
    add_common_auth(info_parser)
    add_path_arg(info_parser)

    unpublish_parser = subparsers.add_parser("unpublish", help="Unpublish a resource")
    add_common_auth(unpublish_parser)
    add_path_arg(unpublish_parser)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    disk = YandexDisk(
        token_file=args.token_file,
        account=args.account,
        auth_dir=args.auth_dir,
    )

    try:
        if args.command == "publish":
            result = disk.publish_file(**_build_share_kwargs(args))
        elif args.command == "update":
            result = disk.update_share_settings(**_build_share_kwargs(args))
        elif args.command == "info":
            result = disk.get_share_info(args.path)
        elif args.command == "unpublish":
            result = disk.unpublish_file(args.path)
        else:
            parser.error(f"Unsupported command: {args.command}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
