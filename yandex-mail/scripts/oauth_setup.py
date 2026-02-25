#!/usr/bin/env python3
"""
Yandex OAuth Token Setup.

Generates OAuth tokens and stores them in a per-account token file.
Each account file uses flat keys for service tokens.

Token file format:
    {
      "email": "user@yandex.ru",
      "token.mail": "y0_...",
      "token.disk": "y0_..."
    }

Usage:
    python oauth_setup.py --client-id YOUR_ID --email user@yandex.ru --account bdi --service mail
    python oauth_setup.py --client-id YOUR_ID --email user@yandex.ru --account bdi --service disk

App registration: https://yandex.ru/dev/id/doc/ru/register-api
Create new key:   https://oauth.yandex.ru/client/new/api
View tokens:      https://oauth.yandex.ru/
"""

import argparse
import json
import sys
from pathlib import Path


SERVICE_SCOPES = {
    "mail": "mail:imap_ro",
    "disk": "cloud_api:disk.read",
}


def _find_config() -> Path:
    """Walk up from script to find config.json at yandex-skills/ root."""
    p = Path(__file__).resolve().parent
    for _ in range(5):
        candidate = p / "config.json"
        if candidate.exists():
            return candidate
        p = p.parent
    raise FileNotFoundError("config.json not found in parent directories")


def _resolve_data_dir(config: dict, config_path: Path) -> Path:
    """Resolve data_dir from config, relative to config file location."""
    data_dir = config.get("data_dir", "data")
    return (config_path.parent / data_dir).resolve()


def generate_auth_url(oauth_base: str, client_id: str, service: str) -> str:
    """Generate Yandex OAuth authorization URL for a specific service."""
    scope = SERVICE_SCOPES.get(service, service)
    return (
        f"{oauth_base}"
        f"?response_type=token&client_id={client_id}&scope={scope}"
    )


def load_token_file(path: Path) -> dict:
    """Load existing token file or return empty structure."""
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    return {"email": ""}


def save_token_file(data: dict, path: Path):
    """Save token file with secure permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(
        description="Set up Yandex OAuth token (per-account, per-service)",
    )
    parser.add_argument("--client-id", required=True, help="OAuth ClientID")
    parser.add_argument("--email", required=True, help="Yandex email address")
    parser.add_argument(
        "--account", required=True,
        help="Account name (e.g. 'bdi') — used as token filename",
    )
    parser.add_argument(
        "--service", required=True,
        choices=list(SERVICE_SCOPES.keys()),
        help="Service to authorize (mail or disk)",
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to config.json (auto-discovers if omitted)",
    )
    args = parser.parse_args()

    # Load shared config for URLs and data_dir
    try:
        config_path = Path(args.config) if args.config else _find_config()
        config = json.loads(config_path.read_text())
        data_dir = _resolve_data_dir(config, config_path)
        oauth_base = config.get("urls", {}).get("oauth", "https://oauth.yandex.ru/authorize")
    except FileNotFoundError:
        data_dir = Path("data")
        oauth_base = "https://oauth.yandex.ru/authorize"

    scope = SERVICE_SCOPES[args.service]
    auth_url = generate_auth_url(oauth_base, args.client_id, args.service)

    print("=" * 70)
    print(f"Yandex OAuth Token Setup — {args.account}/{args.service}")
    print("=" * 70)
    print(f"\nEmail:   {args.email}")
    print(f"Account: {args.account}")
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

    # Token path: {data_dir}/auth/{account}.token
    token_path = data_dir / "auth" / f"{args.account}.token"

    # Load existing file (preserves other service tokens)
    data = load_token_file(token_path)
    data["email"] = args.email
    data[f"token.{args.service}"] = token

    save_token_file(data, token_path)

    token_keys = [k for k in data if k.startswith("token.")]
    services = [k.split(".", 1)[1] for k in token_keys]
    print(f"\nToken saved to: {token_path} (permissions: 600)")
    print(f"Services in this file: {', '.join(services)}")
    print("Token expires after ~1 year. Re-run this script to refresh.")
    print("=" * 70)


if __name__ == "__main__":
    main()
