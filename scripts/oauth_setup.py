#!/usr/bin/env python3
"""
Yandex OAuth token setup.

Generates per-account OAuth tokens and stores the verified token-value to
client_id binding used by the shared Yandex auth resolver.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.auth import load_token_file, save_token_file, token_refs
from common.config import bootstrap_runtime_context, choose_account_alias, find_token_account_by_email
from common.oauth_apps import (
    list_service_profiles,
    oauth_app_for_client_id,
    plan_oauth_app_setup,
    plan_oauth_setup,
)
from common.oauth_token_import import import_managed_oauth_token


def _read_access_token(prompt: str) -> str:
    """Read an OAuth access token without echoing it."""
    return getpass.getpass(prompt)


def _print_warnings(warnings: list[str]) -> None:
    """Print warning lines to stderr."""
    if warnings:
        print("Warnings:", file=sys.stderr)
        for warning in warnings:
            print(f"  - {warning}", file=sys.stderr)


def _format_custom_app(scopes: list[str]) -> str:
    """Return the compact label for a non-shipped OAuth app."""
    return f"custom({', '.join(scopes)})" if scopes else "custom()"


def _account_apps(config: dict[str, object], token_data: dict[str, object]) -> list[str]:
    """Return configured app labels present in an account token file."""
    apps: set[str] = set()
    for ref in token_refs(token_data):
        app = oauth_app_for_client_id(config, ref.client_id)
        if app is None:
            apps.add("custom()")
        elif app.app_id.startswith("custom-") or not app.services:
            apps.add(_format_custom_app(app.scopes))
        else:
            apps.add(app.app_id)
    return sorted(apps)


def _print_account_info(
    alias: str,
    token_data: dict[str, object],
    *,
    config: dict[str, object],
) -> None:
    """Print compact account summary JSON."""
    info: dict[str, object] = {"alias": alias}
    email = str(token_data.get("email") or "").strip()
    if email:
        info["email"] = email
    info["apps"] = _account_apps(config, token_data)
    print(json.dumps(info, ensure_ascii=False, separators=(",", ":")))


def main() -> None:
    """Run the Yandex OAuth setup command-line interface."""
    parser = argparse.ArgumentParser(
        description="Bootstrap Yandex data dir or set up OAuth app managed auth",
    )
    parser.add_argument("--client-id", help="OAuth ClientID")
    parser.add_argument("--email", help="Yandex email address")
    parser.add_argument(
        "--account",
        help="Account alias used as token filename",
    )
    parser.add_argument(
        "--accounts",
        choices=("list", "delete", "reset"),
        help="Manage token-file account aliases",
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
        help="Explicit Yandex data directory override for non-CWD execution",
    )
    parser.add_argument(
        "--from-env",
        metavar="ENV_VAR",
        help="Import an environment OAuth token into managed auth",
    )
    args = parser.parse_args()

    if args.from_env:
        args.from_env = args.from_env.strip()
        if not args.from_env:
            parser.error("--from-env requires an environment variable name")

    has_oauth_args = (
        args.service is not None
        or args.app is not None
        or args.client_id is not None
        or bool(args.scopes)
        or args.from_env is not None
    )
    if args.accounts and (args.email is not None or has_oauth_args):
        parser.error("--accounts cannot be combined with OAuth setup arguments")
    if args.accounts == "delete" and args.account is None:
        parser.error("--accounts delete requires --account <alias>")
    if args.accounts in {"list", "reset"} and args.account is not None:
        parser.error(f"--accounts {args.accounts} does not use --account")

    runtime = bootstrap_runtime_context(
        __file__,
        account=None if args.accounts else args.account,
        email=args.email,
        cwd=Path.cwd(),
        data_dir_override=args.data_dir,
    )
    config = runtime.config
    data_dir = runtime.data_dir

    if args.accounts:
        token_paths = sorted((data_dir / "auth").glob("*.token"))
        if args.accounts == "list":
            for token_path in token_paths:
                print(token_path.stem)
            return
        if args.accounts == "reset":
            for token_path in token_paths:
                token_path.unlink()
            print(f"reset {len(token_paths)}")
            return
        alias = str(args.account or "").strip()
        if not alias or Path(alias).name != alias:
            parser.error("--accounts delete requires a plain --account <alias>")
        token_path = data_dir / "auth" / f"{alias}.token"
        if not token_path.exists():
            print(f"missing {alias}", file=sys.stderr)
            sys.exit(2)
        token_path.unlink()
        print(f"deleted {alias}")
        return

    has_identity_args = any(value is not None for value in (args.email, args.account))
    if args.app and args.service is None and (args.client_id or args.scopes):
        parser.error("--app without --service cannot be combined with --client-id or --scope")

    if not has_identity_args and not has_oauth_args:
        print(data_dir)
        return

    if not has_oauth_args:
        normalized_email = str(args.email or "").strip()
        requested_account = str(args.account or "").strip()
        existing_account = None if requested_account else (
            find_token_account_by_email(data_dir, normalized_email)
            if normalized_email
            else None
        )
        if requested_account:
            resolved_account = requested_account
        elif existing_account is not None:
            resolved_account = existing_account["alias"]
        elif normalized_email:
            resolved_account = choose_account_alias(
                data_dir,
                normalized_email,
                preferred_name=requested_account or None,
            )
        else:
            resolved_account = requested_account
        if not resolved_account or Path(resolved_account).name != resolved_account:
            parser.error("--account must be a plain alias")

        token_path = data_dir / "auth" / f"{resolved_account}.token"
        try:
            token_data = load_token_file(token_path)
        except FileNotFoundError:
            token_data = {}
        if normalized_email:
            token_data["email"] = normalized_email
        save_token_file(token_path, token_data)

        _print_account_info(resolved_account, token_data, config=config)
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

    if not args.from_env:
        display_account = args.account or "<auto>"
        display_service = args.service or (plan.service if plan is not None else "<verify from token>")
        print("=" * 70)
        print(f"Yandex OAuth Managed Auth Setup — {display_account}/{display_service}")
        print("=" * 70)
        print(f"\nAccount: {display_account}")
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

    warnings = import_result.warnings
    _print_warnings(warnings)
    print(import_result.resolved_account)


if __name__ == "__main__":
    main()
