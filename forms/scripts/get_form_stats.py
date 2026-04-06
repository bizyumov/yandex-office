#!/usr/bin/env python3
"""
Get response statistics for specific form(s).
Can be used to manually check forms and get monthly totals.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests

FORMS_API = "https://api.forms.yandex.net/v1"

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.auth import resolve_token
from common.config import load_runtime_context


def check_form_type(form_id: str) -> tuple:
    """
    Check if form ID appears to be from a personal form URL.
    Returns (is_personal, warning_message)
    """
    # Personal forms have URLs like /u/FORM_ID
    # Business forms have URLs like /surveys/FORM_ID
    
    # This is a heuristic - if the form returns 404, it might be personal
    # We can't know for sure without trying, but we can warn based on URL patterns
    # that the user might have used
    return (None, "")  # We'll add better detection based on API response


def get_form_info(form_id: str, token: str) -> Optional[dict]:
    """Get form settings/info from API."""
    url = f"{FORMS_API}/surveys/{form_id}"
    headers = {"Authorization": f"OAuth {token}"}
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json()
    elif response.status_code == 404:
        return None
    else:
        raise RuntimeError(f"Failed to get form info: {response.status_code}")


def get_form_answers(form_id: str, token: str, limit: int = 1000) -> Optional[dict]:
    """Get form answers with pagination."""
    url = f"{FORMS_API}/surveys/{form_id}/answers"
    headers = {"Authorization": f"OAuth {token}"}
    
    all_answers = []
    next_url = None
    total_count = None
    
    while True:
        if next_url:
            response = requests.get(f"{FORMS_API}{next_url}", headers=headers)
        else:
            response = requests.get(url, headers=headers, params={"page_size": 100})
        
        if response.status_code == 200:
            data = response.json()
            answers = data.get("answers", [])
            all_answers.extend(answers)
            
            if total_count is None:
                total_count = data.get("count", len(answers))
            
            # Check if we've reached the limit
            if limit and len(all_answers) >= limit:
                all_answers = all_answers[:limit]
                break
            
            # Check for next page
            next_data = data.get("next")
            if next_data and next_data.get("next_url"):
                next_url = next_data["next_url"]
            else:
                break
        elif response.status_code == 404:
            return None
        elif response.status_code == 403:
            return {"error": "no_access"}
        else:
            raise RuntimeError(f"Failed to get answers: {response.status_code}")
    
    return {
        "answers": all_answers,
        "count": total_count or len(all_answers)
    }


def get_monthly_totals(form_id: str, token: str, limit: int = 1000) -> Dict:
    """
    Get response totals grouped by month.
    Returns detailed stats with monthly breakdown.
    """
    data = get_form_answers(form_id, token, limit)
    if not data or "error" in data:
        return {"error": data.get("error", "unknown") if data else "no_data"}
    
    monthly = {}
    answers = data.get("answers", [])
    
    for answer in answers:
        created = answer.get("created", "")
        if created:
            try:
                # Handle ISO format
                if "Z" in created:
                    created = created.replace("Z", "+00:00")
                dt = datetime.fromisoformat(created)
                month_key = dt.strftime("%Y-%m")
                
                if month_key not in monthly:
                    monthly[month_key] = {
                        "count": 0,
                        "first_response": created,
                        "last_response": created
                    }
                
                monthly[month_key]["count"] += 1
                if created < monthly[month_key]["first_response"]:
                    monthly[month_key]["first_response"] = created
                if created > monthly[month_key]["last_response"]:
                    monthly[month_key]["last_response"] = created
                    
            except ValueError:
                pass
    
    total_count = data.get("count", len(answers))
    has_more = len(answers) < total_count
    
    return {
        "monthly": monthly,
        "total_responses": total_count,
        "fetched_responses": len(answers),
        "has_more": has_more
    }


def get_form_stats(form_id: str, token: str, limit: int = 1000) -> dict:
    """Get comprehensive stats for a form."""
    form_info = get_form_info(form_id, token)
    
    if not form_info:
        return {
            "form_id": form_id,
            "accessible": False,
            "error": "Form not found or no access"
        }
    
    stats = get_monthly_totals(form_id, token, limit)
    
    return {
        "form_id": form_id,
        "accessible": True,
        "title": form_info.get("title", "Unknown"),
        "status": form_info.get("status", "unknown"),
        "created": form_info.get("created"),
        "updated": form_info.get("updated"),
        "stats": stats
    }


def print_summary(results: List[dict]):
    """Print formatted summary."""
    print(f"\n{'='*70}")
    print(f"Yandex Forms Response Statistics")
    print(f"{'='*70}\n")
    
    for result in results:
        form_id = result.get("form_id")
        
        if not result.get("accessible"):
            print(f"❌ Form {form_id}: Not accessible")
            print(f"   Error: {result.get('error', 'Unknown')}")
            # Check if it might be a personal form
            print(f"\n   💡 Hint: This might be a Личная форма (Personal Form).")
            print(f"      The API only works with Формы для бизнеса (Business Forms).")
            print(f"      Check the URL: /u/... = Personal (not supported)")
            print(f"                     /surveys/... = Business (supported)")
            print()
            continue
        
        title = result.get("title", "Unknown")
        stats = result.get("stats", {})
        total = stats.get("total_responses", 0)
        monthly = stats.get("monthly", {})
        
        print(f"📋 {title}")
        print(f"   ID: {form_id}")
        print(f"   Status: {result.get('status', 'unknown')}")
        print(f"   Total responses: {total}")
        
        if monthly:
            print(f"\n   Monthly breakdown:")
            print(f"   {'Month':<12} {'Count':>8} {'First':>22} {'Last':>22}")
            print(f"   {'-'*70}")
            for month in sorted(monthly.keys(), reverse=True):
                mdata = monthly[month]
                first = mdata.get("first_response", "")[:19].replace("T", " ")
                last = mdata.get("last_response", "")[:19].replace("T", " ")
                print(f"   {month:<12} {mdata['count']:>8} {first:>22} {last:>22}")
        
        if stats.get("has_more"):
            print(f"\n   ⚠️  Showing {stats.get('fetched_responses')} of {total} responses")
        
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Get response statistics for Yandex Forms"
    )
    parser.add_argument(
        "--form-id",
        action="append",
        help="Form ID (can be specified multiple times)"
    )
    parser.add_argument(
        "--account",
        required=True,
        help="Account name (e.g., mary)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Max responses to fetch per form (default: 1000)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file (JSON)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON"
    )
    parser.add_argument(
        "--data-dir",
        help="Explicit Yandex data directory override for non-workspace execution",
    )
    
    args = parser.parse_args()
    
    if not args.form_id:
        print("Error: At least one --form-id is required", file=sys.stderr)
        print("\nUsage examples:", file=sys.stderr)
        print(f"  {sys.argv[0]} --form-id FORM_ID_1 --form-id FORM_ID_2 --account mary", file=sys.stderr)
        sys.exit(1)
    
    try:
        runtime = load_runtime_context(
            __file__,
            data_dir_override=args.data_dir,
            require_agent_config=True,
            require_external_data_dir=True,
        )
        data_dir = runtime.data_dir
        token = resolve_token(
            account=args.account,
            skill="forms",
            data_dir=data_dir,
            config=runtime.config,
            required_scopes=["forms:read"],
        ).token
        
        results = []
        for form_id in args.form_id:
            print(f"Fetching stats for {form_id}...", file=sys.stderr)
            result = get_form_stats(form_id, token, args.limit)
            results.append(result)
        
        if args.json or args.output:
            output = {
                "account": args.account,
                "queried_at": datetime.now().isoformat(),
                "forms": results
            }
            if args.output:
                with open(args.output, "w") as f:
                    json.dump(output, f, indent=2, ensure_ascii=False)
                print(f"Saved to {args.output}")
            else:
                print(json.dumps(output, indent=2, ensure_ascii=False))
        else:
            print_summary(results)
            
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
