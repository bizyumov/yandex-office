#!/usr/bin/env python3
"""
Clone a personal form to business forms using the API.
Requires forms:write scope.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import requests

FORMS_API = "https://api.forms.yandex.net/v1"

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.auth import resolve_token
from common.config import load_runtime_context


def get_public_form(form_id: str) -> dict:
    """Get form structure from public endpoint."""
    url = f"{FORMS_API}/surveys/{form_id}/form"
    resp = requests.get(url)
    
    if resp.status_code == 200:
        return resp.json()
    else:
        raise RuntimeError(f"Failed to get form: {resp.status_code} - {resp.text}")


def create_business_form(form_data: dict, token: str) -> dict:
    """Create a new business form with the given structure."""
    # The API doesn't have a direct "create form" endpoint documented
    # Let's try the surveys endpoint
    url = f"{FORMS_API}/surveys"
    headers = {"Authorization": f"OAuth {token}", "Content-Type": "application/json"}
    
    # Try to create form with basic data
    payload = {
        "name": form_data.get("name", "New Form"),
        "pages": form_data.get("pages", []),
        "styles": form_data.get("styles", {}),
        "texts": form_data.get("texts", {}),
        "teaser": form_data.get("teaser", True),
        "footer": form_data.get("footer", True),
    }
    
    resp = requests.post(url, json=payload, headers=headers)
    
    if resp.status_code in [200, 201]:
        return resp.json()
    elif resp.status_code == 404:
        # Endpoint might not exist or different path
        raise RuntimeError(f"Create endpoint not found (404). API may not support form creation.")
    else:
        raise RuntimeError(f"Failed to create form: {resp.status_code} - {resp.text}")


def main():
    parser = argparse.ArgumentParser(
        description="Clone a personal Yandex Form to Business Forms"
    )
    parser.add_argument(
        "--source-form-id",
        required=True,
        help="Source personal form ID"
    )
    parser.add_argument(
        "--account",
        required=True,
        help="Account name for business forms"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Save form structure to file"
    )
    parser.add_argument(
        "--data-dir",
        help="Explicit Yandex data directory override for non-workspace execution",
    )
    
    args = parser.parse_args()
    
    try:
        runtime = load_runtime_context(
            __file__,
            data_dir_override=args.data_dir,
            require_agent_config=True,
            require_external_data_dir=True,
        )
        token = resolve_token(
            account=args.account,
            skill="forms",
            data_dir=runtime.data_dir,
            config=runtime.config,
            required_scopes=["forms:write"],
        ).token
        
        # Step 1: Get public form structure
        print(f"Fetching form {args.source_form_id}...", file=sys.stderr)
        form_data = get_public_form(args.source_form_id)
        
        print(f"Form title: {form_data.get('name')}", file=sys.stderr)
        print(f"Pages: {len(form_data.get('pages', []))}", file=sys.stderr)
        
        # Save structure if requested
        if args.output:
            with open(args.output, "w") as f:
                json.dump(form_data, f, indent=2, ensure_ascii=False)
            print(f"Saved structure to {args.output}", file=sys.stderr)
        
        # Step 2: Try to create business form
        print(f"\nAttempting to create business form...", file=sys.stderr)
        try:
            result = create_business_form(form_data, token)
            print(f"\n✅ Business form created successfully!")
            print(f"New Form ID: {result.get('id')}")
            print(json.dumps(result, indent=2, ensure_ascii=False))
        except RuntimeError as e:
            print(f"\n❌ Could not create form via API: {e}")
            print("\nThe Yandex Forms API may not support programmatic form creation.")
            print("You may need to manually recreate this form in:")
            print("  https://forms.yandex.ru/cloud/admin")
            
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
