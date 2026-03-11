#!/usr/bin/env python3
"""
Yandex OAuth token setup.

Generates per-account service tokens and records scope metadata used by the
shared Yandex auth resolver.
"""

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.auth import (
    canonical_token_key,
    default_scopes,
    load_token_file,
    save_token_file,
    set_token_metadata,
)
from common.config import load_runtime_context


SERVICE_SCOPES = {
    "auth": [],
    "calendar": default_scopes("calendar", "read"),
    "contacts": default_scopes("contacts", "read"),
    "directory": default_scopes("directory", "read"),
    "disk": default_scopes("disk", "read"),
    "forms": default_scopes("forms", "read"),
    "mail": default_scopes("mail", "read"),
    "telemost": default_scopes("telemost", "write"),
    "tracker": default_scopes("tracker", "read"),
}


def generate_auth_url(oauth_base: str, client_id: str, scopes: list[str]) -> str:
    scope_arg = " ".join(scopes)
    return (
        f"{oauth_base}"
        f"?response_type=token&client_id={client_id}&scope={scope_arg}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set up Yandex OAuth token (per-account, per-service)",
    )
    parser.add_argument("--client-id", required=True, help="OAuth ClientID")
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
        "--scope",
        action="append",
        dest="scopes",
        default=[],
        help="Additional OAuth scope (required with --service auth)",
    )
    args = parser.parse_args()

    runtime = load_runtime_context(__file__)
    config = runtime.config
    data_dir = runtime.data_dir
    oauth_base = config.get("urls", {}).get(
        "oauth",
        "https://oauth.yandex.ru/authorize",
    )

    scopes = sorted({*SERVICE_SCOPES[args.service], *args.scopes})
    if args.service == "auth" and not scopes:
        print("Error: --service auth requires at least one --scope", file=sys.stderr)
        sys.exit(2)

    auth_url = generate_auth_url(oauth_base, args.client_id, scopes)

    print("=" * 70)
    print(f"Yandex OAuth Token Setup — {args.account}/{args.service}")
    print("=" * 70)
    print(f"\nEmail:   {args.email}")
    print(f"Account: {args.account}")
    print(f"Service: {args.service}")
    print(f"Scope:   {' '.join(scopes) if scopes else '(none)'}")
    print("\nInstructions:")
    print("  1. Open the URL below in your browser")
    print("  2. Log in with your Yandex account")
    print("  3. Grant the requested permissions")
    print("  4. Copy the access_token from the redirect URL")
    print(f"\nAuthorization URL:\n\n  {auth_url}\n")
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
    token_data["oauth_client_id"] = args.client_id
    set_token_metadata(
        token_data,
        token_key,
        scopes=scopes,
        client_id=args.client_id,
        oauth_base=oauth_base,
    )
    save_token_file(token_path, token_data)

    services = sorted(key.split(".", 1)[1] for key in token_data if key.startswith("token."))
    print(f"\nToken saved to: {token_path} (permissions: 600)")
    print(f"Services in this file: {', '.join(services)}")
    print("Token expires after ~1 year. Re-run this script to refresh.")
    print("=" * 70)


if __name__ == "__main__":
    main()
