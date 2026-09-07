#!/usr/bin/env python3
"""Update a Yandex 360 Directory user — including the public name (displayName).

This is the capability the Yandex 360 web UI lacks: changing a user's public
name and other Directory fields via the API. Token selection and the correct
host (``api360.yandex.net``) are handled by ``DirectoryApi``.

Usage::

    python update_user.py --account alice --org-id 123456 \\
        --user-id 1120000000000001 --display-name "Имя Фамилия"

Note: ``displayName`` is set-only (cannot be cleared) and is moderated by Yandex
ID — values containing brand/company/official-title/trademark names are
auto-reverted. See ``directory/directory.md``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from directory.scripts.list import DirectoryApi  # noqa: E402


def build_update_body(args: argparse.Namespace) -> dict[str, Any]:
    """Translate update CLI flags into a Directory PATCH body."""
    body: dict[str, Any] = {}
    if args.display_name is not None:
        body["displayName"] = args.display_name
    if args.position is not None:
        body["position"] = args.position
    if args.about is not None:
        body["about"] = args.about
    if args.department_id is not None:
        body["departmentId"] = int(args.department_id)
    if args.is_admin is not None:
        body["isAdmin"] = args.is_admin == "true"
    if args.is_enabled is not None:
        body["isEnabled"] = args.is_enabled == "true"
    return body


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Update a Yandex 360 Directory user. Can set the public name "
            "(displayName), which the Yandex 360 web UI cannot change."
        ),
    )
    parser.add_argument("--account", "-a", help="Account alias (auth/{account}.token)")
    parser.add_argument("--data-dir", help="Explicit Yandex data directory override")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    parser.add_argument("--user-id", required=True, help="User id to update")
    parser.add_argument("--org-id", help="Organization id (auto-discovered if omitted)")

    parser.add_argument("--display-name", help="Public name (displayName). Set-only; Yandex-ID-moderated.")
    parser.add_argument("--position", help="Job title")
    parser.add_argument("--about", help="About / description")
    parser.add_argument("--department-id", help="Move user to this department id")
    parser.add_argument("--is-admin", choices=["true", "false"], help="Grant/revoke organization admin")
    parser.add_argument("--is-enabled", choices=["true", "false"], help="Enable/block the account")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    body = build_update_body(args)
    if not body:
        parser.error("specify at least one field to update (e.g. --display-name)")

    api = DirectoryApi(account=args.account, data_dir=args.data_dir)
    org_id = api.resolve_org_id(args.org_id)
    result = api.update_user(org_id, args.user_id, body)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
