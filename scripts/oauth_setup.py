#!/usr/bin/env python3
"""
Yandex OAuth token setup.

Generates per-account service tokens and records scope metadata used by the
shared Yandex auth resolver.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.auth import (
    canonical_token_key,
    load_token_file,
    save_token_file,
    set_token_metadata,
)
from common.config import load_runtime_context
from common.oauth_setup import SERVICE_SCOPES, plan_oauth_setup


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set up Yandex OAuth token (per-account, per-service)",
    )
    parser.add_argument("--client-id", help="OAuth ClientID")
    parser.add_argument("--email", required=True, help="Yandex email address")
    parser.add_argument(
        "--account",
        required=True,
        help="Account name used as token filename",
    )
    parser.add_argument(
        "--service",
        required=True,
        choices=sorted(SERVICE_SCOPES.keys()),
        help="Service token to authorize",
    )
    parser.add_argument(
        "--app",
        help="Preconfigured OAuth app id to use instead of the service default",
    )
    parser.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        default=[],
        help="Explicit OAuth scope override",
    )
    args = parser.parse_args()

    runtime = load_runtime_context(__file__)
    config = runtime.config
    data_dir = runtime.data_dir

    try:
        plan = plan_oauth_setup(
            config,
            service=args.service,
            app_id=args.app,
            client_id=args.client_id,
            extra_scopes=args.scopes,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)

    print("=" * 70)
    print(f"Yandex OAuth Token Setup — {args.account}/{args.service}")
    print("=" * 70)
    print(f"\nEmail:   {args.email}")
    print(f"Account: {args.account}")
    print(f"Service: {args.service}")
    print(f"Mode:    {plan.mode}")
    if plan.app_id:
        print(f"App ID:  {plan.app_id}")
    if plan.app_name:
        print(f"App:     {plan.app_name}")
    print(f"Client:  {plan.client_id}")
    print(f"Scope:   {' '.join(plan.scopes) if plan.scopes else '(none)'}")
    print("\nInstructions:")
    print("  1. Open the URL below in your browser")
    print("  2. Log in with your Yandex account")
    print("  3. Grant the requested permissions")
    print("  4. Copy the access_token from the redirect URL")
    if plan.mode == "configured_app" and not plan.include_scope_in_url:
        print("  Note: this URL relies on the OAuth app's baked-in scope set")
    print(f"\nAuthorization URL:\n\n  {plan.auth_url}\n")
    print("=" * 70)

    token = input("\nPaste the access_token here: ").strip()
    if not token:
        print("Error: Token cannot be empty", file=sys.stderr)
        sys.exit(1)

    token_path = data_dir / "auth" / f"{args.account}.token"
    token_data = load_token_file(token_path)
    token_key = canonical_token_key(args.service)

    token_data["email"] = args.email
    token_data[token_key] = token
    token_data["oauth_client_id"] = plan.client_id
    set_token_metadata(
        token_data,
        token_key,
        scopes=plan.scopes,
        client_id=plan.client_id,
        app_id=plan.app_id,
        oauth_base=config.get("urls", {}).get(
            "oauth",
            "https://oauth.yandex.ru/authorize",
        ),
    )
    save_token_file(token_path, token_data)

    services = sorted(
        key.split(".", 1)[1] for key in token_data if key.startswith("token.")
    )
    print(f"\nToken saved to: {token_path} (permissions: 600)")
    print(f"Services in this file: {', '.join(services)}")
    print("Token expires after ~1 year. Re-run this script to refresh.")
    print("=" * 70)


if __name__ == "__main__":
    main()
