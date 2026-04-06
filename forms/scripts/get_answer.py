#!/usr/bin/env python3
"""
Get a single answer from Yandex Forms API.
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


def get_answer(answer_id: int, token: str) -> dict:
    """Get answer data by ID."""
    url = f"{FORMS_API}/answers"
    headers = {"Authorization": f"OAuth {token}"}
    params = {"answer_id": answer_id}
    
    response = requests.get(url, params=params, headers=headers)
    
    if response.status_code == 200:
        return response.json()
    elif response.status_code == 401:
        raise PermissionError("Invalid or expired OAuth token")
    elif response.status_code == 404:
        raise FileNotFoundError(f"Answer {answer_id} not found")
    else:
        raise RuntimeError(f"Failed to get answer: {response.status_code}")


def main():
    parser = argparse.ArgumentParser(
        description="Get a single answer from Yandex Forms"
    )
    parser.add_argument(
        "--answer-id",
        type=int,
        required=True,
        help="Answer ID"
    )
    parser.add_argument(
        "--account",
        required=True,
        help="Account name (e.g., mary)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file (JSON)"
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
            required_scopes=["forms:read"],
        ).token
        
        answer = get_answer(args.answer_id, token)
        
        if args.output:
            with open(args.output, "w") as f:
                json.dump(answer, f, indent=2, ensure_ascii=False)
            print(f"Saved to {args.output}")
        else:
            print(json.dumps(answer, indent=2, ensure_ascii=False))
            
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
