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
from common.config import bootstrap_runtime_context
from common.oauth_apps import SERVICE_SCOPES, list_service_profiles, plan_oauth_setup


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap Yandex data dir or set up a per-account, per-service OAuth token",
    )
    parser.add_argument("--client-id", help="OAuth ClientID")
    parser.add_argument("--email", help="Yandex email address")
    parser.add_argument(
        "--account",
        help="Account name used as token filename",
    )
    parser.add_argument(
        "--service",
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
    parser.add_argument(
        "--data-dir",
        help="Explicit Yandex data directory override for non-workspace execution",
    )
    args = parser.parse_args()

    has_identity_args = any(value is not None for value in (args.email, args.account))
    if has_identity_args and not all(value is not None for value in (args.email, args.account)):
        parser.error("--email and --account must be provided together")
    if args.service is not None and not has_identity_args:
        parser.error("--service requires --email and --account")

    runtime = bootstrap_runtime_context(
        __file__,
        account=args.account,
        email=args.email,
        cwd=Path.cwd(),
        data_dir_override=args.data_dir,
    )
    config = runtime.config
    data_dir = runtime.data_dir

    if not has_identity_args:
        print("=" * 70)
        print("Yandex bootstrap complete")
        print("=" * 70)
        print(f"\nData dir: {data_dir}")
        print(f"Agent config: {runtime.agent_config_path}")
        print("\nNext step:")
        print(
            "  Re-run this script with --email and --account to add a Yandex account, "
            "or add --service to issue a service token immediately."
        )
        print("=" * 70)
        return

    if args.service is None:
        print("=" * 70)
        print("Yandex account added")
        print("=" * 70)
        print(f"\nData dir: {data_dir}")
        print(f"Account:  {args.account}")
        print(f"Email:    {args.email}")
        print("\nNext step:")
        print(
            "  Re-run this script with --email, --account, and --service to issue "
            "a service token for this account."
        )
        print("=" * 70)
        return

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

    if plan.mode == "configured_app":
        profiles = list_service_profiles(config, args.service)
        default_profile = next((item for item in profiles if item.is_default), None)
        other_profiles = [item for item in profiles if not item.is_default]
        if default_profile is not None:
            print("\nDefault profile:")
            print(f"  - {default_profile.app_id}")
            print(f"  - {default_profile.access_class}")
            print(f"  - {default_profile.auth_url}")
        if other_profiles:
            print("\nOther profiles:")
            for profile in other_profiles:
                print(f"  - {profile.app_id} — {profile.access_class}")
                print(f"    {profile.auth_url}")
            print(
                "\nIf you choose another profile, re-run this script with "
                f"--app <profile_id> before saving the token."
            )

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
    try:
        token_data = load_token_file(token_path)
    except FileNotFoundError:
        token_data = {"email": args.email}
    token_key = canonical_token_key(args.service)

    token_data["email"] = args.email
    token_data[token_key] = token
    set_token_metadata(
        token_data,
        token_key,
        scopes=plan.scopes,
        client_id=plan.client_id,
        app_id=plan.app_id,
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
