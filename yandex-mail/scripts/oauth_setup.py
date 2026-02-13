#!/usr/bin/env python3
"""
Yandex OAuth Token Setup.

Generates OAuth tokens for Yandex services (Mail, Disk, etc.).
Saves tokens to auth/{service_name}.token

Usage:
    # For mail (IMAP access)
    python oauth_setup.py --client-id YOUR_ID --email user@yandex.ru --service mail

    # For disk (read access)
    python oauth_setup.py --client-id YOUR_ID --email user@yandex.ru --service disk

App registration: https://yandex.ru/dev/id/doc/ru/register-api
Create new key:   https://oauth.yandex.ru/client/new/api
View tokens:      https://oauth.yandex.ru/
"""

import argparse
import json
import sys
from pathlib import Path


SERVICE_SCOPES = {
    "mail": "mail:imap_full",
    "disk": "disk:read",
}


def generate_auth_url(client_id: str, service: str) -> str:
    """Generate Yandex OAuth authorization URL."""
    scope = SERVICE_SCOPES.get(service, service)
    return (
        f"https://oauth.yandex.ru/authorize"
        f"?response_type=token&client_id={client_id}&scope={scope}"
    )


def save_token(email_addr: str, token: str, output_path: Path):
    """Save token to JSON file with secure permissions."""
    token_data = {"email": email_addr, "token": token}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(token_data, indent=2))
    output_path.chmod(0o600)
    print(f"Token saved to: {output_path} (permissions: 600)")


def main():
    parser = argparse.ArgumentParser(
        description="Set up Yandex OAuth token",
    )
    parser.add_argument("--client-id", required=True, help="OAuth ClientID")
    parser.add_argument("--email", required=True, help="Yandex email address")
    parser.add_argument(
        "--service",
        default="mail",
        choices=list(SERVICE_SCOPES.keys()),
        help="Service to authorize (default: mail)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to save token (default: data/auth/)",
    )
    args = parser.parse_args()

    auth_url = generate_auth_url(args.client_id, args.service)
    scope = SERVICE_SCOPES[args.service]

    print("=" * 70)
    print(f"Yandex OAuth Token Setup — {args.service}")
    print("=" * 70)
    print(f"\nEmail:   {args.email}")
    print(f"Service: {args.service}")
    print(f"Scope:   {scope}")
    print("\nInstructions:")
    print("  1. Open the URL below in your browser")
    print("  2. Log in with your Yandex account")
    print(f"  3. Grant '{scope}' permissions")
    print("  4. Copy the access_token from the redirect URL")
    print(f"\nAuthorization URL:\n\n  {auth_url}\n")
    print("=" * 70)

    token = input("\nPaste the access_token here: ").strip()
    if not token:
        print("Error: Token cannot be empty", file=sys.stderr)
        sys.exit(1)

    # Determine output path
    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        out_dir = Path("data/auth")

    output_path = out_dir / f"{args.service}.token"
    save_token(args.email, token, output_path)

    print(f"\nSetup complete! Token file: {output_path}")
    print("Token expires after ~1 year. Re-run this script to refresh.")
    print("=" * 70)


if __name__ == "__main__":
    main()
