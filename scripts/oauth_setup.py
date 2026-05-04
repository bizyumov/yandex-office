#!/usr/bin/env python3
"""
Yandex OAuth token setup.

Generates per-account OAuth tokens and stores the verified token-value to
client_id binding used by the shared Yandex auth resolver.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.auth import (
    load_token_file,
    save_token_file,
)
from common.config import (
    bootstrap_runtime_context,
    choose_account_alias,
    find_token_account_by_email,
)
from common.oauth_apps import (
    list_service_profiles,
    plan_oauth_app_setup,
    plan_oauth_setup,
)
from common.oauth_token_import import import_managed_oauth_token


def _read_access_token(prompt: str) -> str:
    return getpass.getpass(prompt)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap Yandex data dir or set up a per-account OAuth app token",
    )
    parser.add_argument("--client-id", help="OAuth ClientID")
    parser.add_argument("--email", help="Yandex email address")
    parser.add_argument(
        "--account",
        help="Account name used as token filename",
    )
    parser.add_argument(
        "--service",
        help="Compatibility shortcut: choose the configured default OAuth app for a service",
    )
    parser.add_argument(
        "--app",
        help="Preconfigured OAuth app id to authorize",
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
    parser.add_argument(
        "--from-env",
        metavar="ENV_VAR",
        help="Import a raw OAuth token from an environment variable into managed auth",
    )
    args = parser.parse_args()

    if args.from_env:
        args.from_env = args.from_env.strip()
        if not args.from_env:
            parser.error("--from-env requires an environment variable name")

    runtime = bootstrap_runtime_context(
        __file__,
        account=args.account,
        email=args.email,
        cwd=Path.cwd(),
        data_dir_override=args.data_dir,
    )
    config = runtime.config
    data_dir = runtime.data_dir

    has_oauth_args = (
        args.service is not None
        or args.app is not None
        or args.client_id is not None
        or bool(args.scopes)
        or args.from_env is not None
    )
    has_identity_args = any(value is not None for value in (args.email, args.account))
    if not has_oauth_args and has_identity_args and not all(
        value is not None for value in (args.email, args.account)
    ):
        parser.error("--email and --account must be provided together")

    if args.app and args.service is None and (args.client_id or args.scopes):
        parser.error("--app without --service cannot be combined with --client-id or --scope")

    if not has_identity_args and not has_oauth_args:
        print("=" * 70)
        print("Yandex bootstrap complete")
        print("=" * 70)
        print(f"\nData dir: {data_dir}")
        print(f"Agent config: {runtime.agent_config_path}")
        print("\nNext step:")
        print(
            "  Re-run this script with --email, --account, and --app "
            "to issue a token. The verified token email creates or reuses the "
            "account alias."
        )
        print("=" * 70)
        return

    if not has_oauth_args:
        normalized_email = str(args.email or "").strip()
        existing_account = find_token_account_by_email(data_dir, normalized_email)
        warnings: list[str] = []
        if existing_account is not None:
            resolved_account = existing_account["alias"]
            if args.account and args.account != resolved_account:
                warnings.append(
                    f'Provided --account "{args.account}" does not match existing account '
                    f'"{resolved_account}" for {normalized_email}. Using "{resolved_account}".'
                )
        else:
            resolved_account = choose_account_alias(
                data_dir,
                normalized_email,
                preferred_name=args.account,
            )
            if args.account and args.account != resolved_account:
                warnings.append(
                    f'Account name "{args.account}" was unavailable; created "{resolved_account}" for {normalized_email}.'
                )

        token_path = data_dir / "auth" / f"{resolved_account}.token"
        try:
            token_data = load_token_file(token_path)
        except FileNotFoundError:
            token_data = {}
        token_data["email"] = normalized_email
        save_token_file(token_path, token_data)

        print("=" * 70)
        print("Yandex account initialized")
        print("=" * 70)
        print(f"\nData dir: {data_dir}")
        if warnings:
            print("\nWarnings:")
            for warning in warnings:
                print(f"  - {warning}")
        print(f"\nAccount: {resolved_account}")
        print(f"Email:   {normalized_email}")
        print("\nNext step:")
        print(
            "  Re-run this script with --email, --account, and --app to issue "
            "a token. The verified token email will create or reuse the account alias."
        )
        print("=" * 70)
        return

    has_oauth_selector = (
        args.service is not None
        or args.app is not None
        or args.client_id is not None
        or bool(args.scopes)
    )
    plan = None
    if not (args.from_env and not has_oauth_selector):
        try:
            if args.app and args.service is None:
                plan = plan_oauth_app_setup(config, app_id=args.app)
            else:
                if args.service is None:
                    parser.error("--service is required for --client-id/--scope flows")
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

    display_account = args.account or "<auto>"
    display_email = args.email or "<verify from token>"
    display_service = args.service or (plan.service if plan is not None else "<verify from token>")
    print("=" * 70)
    print(f"Yandex OAuth Token Setup — {display_account}/{display_service}")
    print("=" * 70)
    print(f"\nEmail:   {display_email}")
    print(f"Account: {display_account}")
    print(f"Service: {display_service}")

    if plan is not None and plan.mode == "configured_app" and args.service is not None:
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

    print(f"Mode:    {plan.mode if plan is not None else 'env_import'}")
    if plan is not None:
        if plan.app_id:
            print(f"App ID:  {plan.app_id}")
        if plan.app_name:
            print(f"App:     {plan.app_name}")
        print(f"Client:  {plan.client_id}")
        print(f"Scope:   {' '.join(plan.scopes) if plan.scopes else '(none)'}")
    if args.from_env:
        print("Token source: environment variable")
        print("\nThis is a one-time import into managed auth.")
        print("Runtime clients do not send raw-token fallback Authorization headers.")
    else:
        print("\nInstructions:")
        print("  1. Open the URL below in your browser")
        print("  2. Log in with your Yandex account")
        print("  3. Grant the requested permissions")
        print("  4. Copy the access_token from the redirect URL")
        if plan is not None and plan.mode == "configured_app" and not plan.include_scope_in_url:
            print("  Note: this URL relies on the OAuth app's baked-in scope set")
        if plan is not None:
            print(f"\nAuthorization URL:\n\n  {plan.auth_url}\n")
    print("=" * 70)

    if args.from_env:
        token = os.environ.get(args.from_env, "").strip()
        if not token:
            print("Error: Environment variable is empty or unset", file=sys.stderr)
            sys.exit(1)
    else:
        token = _read_access_token("\nPaste the access_token here: ").strip()
    if not token:
        print("Error: Token cannot be empty", file=sys.stderr)
        sys.exit(1)

    try:
        import_result = import_managed_oauth_token(
            config=config,
            data_dir=data_dir,
            agent_config=runtime.agent_config,
            agent_config_path=runtime.agent_config_path,
            token=token,
            email=args.email,
            account=args.account,
            service=args.service,
            selected_app_id=plan.app_id if plan is not None else None,
            selected_scopes=plan.scopes if plan is not None else [],
            permissions_note_provider=lambda: input(
                "Optional: describe the permissions for this custom token (press Enter to skip): "
            ).strip() or None,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    identity = import_result.identity
    warnings = import_result.warnings
    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"  - {warning}")
    if args.from_env:
        print("\nImported token from environment variable")
    print(f"\nVerified email: {identity.email}")
    print(f"Verified client: {identity.client_id}")
    print(f"Resolved account: {import_result.resolved_account}")
    print(f"\nToken saved to: {import_result.token_path} (permissions: 600)")
    print(f"Tokens in this file: {import_result.token_count}")
    print("Token expires after ~1 year. Re-run this script to refresh.")
    print("=" * 70)


if __name__ == "__main__":
    main()
