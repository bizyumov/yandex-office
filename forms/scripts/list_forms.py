#!/usr/bin/env python3
"""
List forms accessible to the account via Yandex Forms API.
"""

import argparse
import json
import sys
from pathlib import Path

import requests

FORMS_API = "https://api.forms.yandex.net/v1"

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.auth import resolve_token
from common.config import load_runtime_context


def get_user_info(token: str) -> dict:
    """Get current user info to verify authentication."""
    url = f"{FORMS_API}/users/me/"
    headers = {"Authorization": f"OAuth {token}"}
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json()
    elif response.status_code == 401:
        raise PermissionError("Invalid or expired OAuth token")
    else:
        raise RuntimeError(f"Failed to get user info: {response.status_code}")


def main():
    parser = argparse.ArgumentParser(
        description="List Yandex Forms accessible to account"
    )
    parser.add_argument(
        "--account",
        required=True,
        help="Account name (e.g., ctiis)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file for form list (JSON)"
    )
    
    args = parser.parse_args()
    
    try:
        runtime = load_runtime_context(__file__)
        token = resolve_token(
            account=args.account,
            skill="forms",
            data_dir=runtime.data_dir,
            config=runtime.config,
            required_scopes=["forms:read"],
        ).token
        
        # Get user info (this verifies the token works)
        user_info = get_user_info(token)
        
        # Note: Yandex Forms API doesn't have a direct "list all forms" endpoint.
        # Forms must be tracked by ID. This script verifies auth is working.
        result = {
            "account": args.account,
            "user": user_info,
            "note": "Yandex Forms API requires form IDs. Store known form IDs in your workflow."
        }
        
        if args.output:
            with open(args.output, "w") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(f"Saved to {args.output}")
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except PermissionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
