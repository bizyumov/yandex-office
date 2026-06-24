#!/usr/bin/env python3
"""Yandex 360 Directory (Директория) managed-auth client + read CLI.

Holds the ``DirectoryApi`` client used by the other Directory scripts. The
Directory API host is read from config (``urls.directory_api`` =
``https://api360.yandex.net``), so the ``cloud-api.yandex.net`` vs
``api360.yandex.net`` mix-up that yields ``404`` cannot occur here.

Usage::

    python list.py --account alice --list-orgs
    python list.py --account alice --org-id 123456 --list-users
    python list.py --account alice --org-id 123456 --user-id 1120000000000001

To change a user's public name (displayName) — which the Yandex 360 web UI
cannot — use ``update_user.py``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

try:
    import requests
except ImportError:  # pragma: no cover - environment guard
    print("Missing dependency: pip install requests", file=sys.stderr)
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.api import YandexApiContext, request_json, yandex_api_method  # noqa: E402
from common.config import load_runtime_context  # noqa: E402

logger = logging.getLogger("YandexDirectory")

# Fallback only; the live value comes from config["urls"]["directory_api"].
API_BASE = "https://api360.yandex.net"


class DirectoryApi:
    """Managed-auth client for the Yandex 360 Directory API."""

    def __init__(self, account: str | None = None, data_dir: str | None = None):
        """Initialize without resolving tokens; decorators own token selection."""
        self.runtime = load_runtime_context(
            __file__,
            data_dir_override=data_dir,
            require_external_data_dir=data_dir is not None,
        )
        self._config = self.runtime.config
        self._data_dir = self.runtime.data_dir
        self.api_base = str(self._config.get("urls", {}).get("directory_api", API_BASE)).rstrip("/")
        self.account = account
        self.session = requests.Session()

    def _api_context(self) -> YandexApiContext:
        """Build the shared API context used by decorated Directory methods."""
        return YandexApiContext(
            account=self.account,
            data_dir=self._data_dir,
            config=self._config,
            session=self.session,
        )

    # ── organization discovery ─────────────────────────────────────────

    @yandex_api_method("directory.organizations.list", one_of=["directory:read_organization"])
    def list_organizations(self, ctx: YandexApiContext) -> dict:
        """GET /directory/v1/org — organizations accessible to this account."""
        return request_json(ctx, "GET", ctx.url("directory_api", "/directory/v1/org"))

    def resolve_org_id(self, org_id: int | str | None) -> str:
        """Return an explicit org id, or discover the first accessible one."""
        if org_id is not None and str(org_id).strip():
            return str(org_id).strip()
        payload = self.list_organizations()
        orgs = payload.get("organizations", []) if isinstance(payload, dict) else (payload or [])
        if not orgs:
            raise RuntimeError("No organization accessible to this account; pass --org-id")
        return str(orgs[0].get("id"))

    # ── users ──────────────────────────────────────────────────────────

    @yandex_api_method("directory.users.list", one_of=["directory:read_users"])
    def list_users(
        self,
        ctx: YandexApiContext,
        org_id: str | int,
        page: int = 1,
        per_page: int = 1000,
    ) -> dict:
        """GET /directory/v1/org/{orgId}/users."""
        url = ctx.url("directory_api", f"/directory/v1/org/{org_id}/users")
        return request_json(ctx, "GET", url, params={"page": page, "perPage": per_page})

    @yandex_api_method("directory.users.get", one_of=["directory:read_users"])
    def get_user(self, ctx: YandexApiContext, org_id: str | int, user_id: str) -> dict:
        """GET /directory/v1/org/{orgId}/users/{userId}."""
        url = ctx.url("directory_api", f"/directory/v1/org/{org_id}/users/{user_id}")
        return request_json(ctx, "GET", url)

    @yandex_api_method("directory.users.update", one_of=["directory:write_users"])
    def update_user(
        self,
        ctx: YandexApiContext,
        org_id: str | int,
        user_id: str,
        body: dict,
    ) -> dict:
        """PATCH /directory/v1/org/{orgId}/users/{userId}.

        Only fields present in ``body`` are changed. ``displayName`` (the public
        name) is the field most often wanted because it cannot be edited in the
        Yandex 360 web UI. It is set-only and moderated by Yandex ID — see
        ``directory/directory.md`` ("displayName (Public Name)").
        """
        url = ctx.url("directory_api", f"/directory/v1/org/{org_id}/users/{user_id}")
        return request_json(ctx, "PATCH", url, json=body)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Yandex 360 Directory read client (organizations & users).",
    )
    parser.add_argument("--account", "-a", help="Account alias (auth/{account}.token)")
    parser.add_argument("--data-dir", help="Explicit Yandex data directory override")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    parser.add_argument("--list-orgs", action="store_true", help="List organizations (discover --org-id)")
    parser.add_argument("--list-users", action="store_true", help="List organization users")
    parser.add_argument("--user-id", help="Read a single user")
    parser.add_argument("--org-id", help="Organization id (auto-discovered if omitted and needed)")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--per-page", type=int, default=1000, help="Items per page (max 1000)")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    api = DirectoryApi(account=args.account, data_dir=args.data_dir)

    if args.list_orgs:
        print(json.dumps(api.list_organizations(), ensure_ascii=False, indent=2))
        return

    if args.list_users:
        org_id = api.resolve_org_id(args.org_id)
        result = api.list_users(org_id, page=args.page, per_page=args.per_page)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.user_id:
        org_id = api.resolve_org_id(args.org_id)
        print(json.dumps(api.get_user(org_id, args.user_id), ensure_ascii=False, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
