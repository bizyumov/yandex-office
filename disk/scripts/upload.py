#!/usr/bin/env python3
"""Upload files to Yandex Disk, optionally publishing them immediately."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from download import DISK_WRITE_SCOPES, YandexDisk
from share import add_common_auth, add_share_options, _build_share_kwargs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Upload files to Yandex Disk")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    add_common_auth(parser)
    parser.add_argument("--local", required=True, help="Local file path to upload")
    parser.add_argument("--remote", required=True, help="Disk destination path (e.g. disk:/Docs/report.pdf)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing remote file")
    parser.add_argument(
        "--no-create-parents",
        action="store_true",
        help="Do not auto-create missing parent directories",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish the uploaded file after upload completes",
    )
    add_share_options(parser)
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
        required_scopes=DISK_WRITE_SCOPES,
    )

    try:
        if args.publish:
            share_kwargs = _build_share_kwargs(
                argparse.Namespace(
                    path=args.remote,
                    access=args.access,
                    org_id=args.org_id,
                    rights=args.rights,
                    password=args.password,
                    available_until=args.available_until,
                    user_ids=args.user_ids,
                    group_ids=args.group_ids,
                    department_ids=args.department_ids,
                )
            )
            share_kwargs.pop("path", None)
            result = disk.upload_and_publish(
                args.local,
                args.remote,
                overwrite=args.overwrite,
                create_parents=not args.no_create_parents,
                **share_kwargs,
            )
        else:
            result = disk.upload_file(
                args.local,
                args.remote,
                overwrite=args.overwrite,
                create_parents=not args.no_create_parents,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
