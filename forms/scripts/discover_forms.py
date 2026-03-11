#!/usr/bin/env python3
"""
Discover forms and get response totals per month.
Scans email archives for form references and queries API for response counts.
"""

import argparse
import base64
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse

import requests

FORMS_API = "https://api.forms.yandex.net/v1"

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.auth import resolve_token
from common.config import load_runtime_context


def decode_tracking_url(url: str) -> Optional[str]:
    """Decode Yandex tracking URL to get actual destination."""
    # Format: https://click.sender.yandex.ru/.../*https://forms.yandex.ru/...
    if "*https://" in url:
        parts = url.split("*")
        if len(parts) >= 2:
            return parts[-1]
    return url


def extract_form_ids_from_file(filepath: Path) -> Set[str]:
    """Extract form IDs from a file."""
    form_ids = set()
    
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception:
        return form_ids
    
    # Pattern 1: Direct forms.yandex.ru/u/FORM_ID
    pattern1 = r'forms\.yandex\.ru/u/([a-zA-Z0-9]+)'
    form_ids.update(re.findall(pattern1, content))
    
    # Pattern 2: forms.yandex.ru/surveys/FORM_ID
    pattern2 = r'forms\.yandex\.ru/surveys/([a-zA-Z0-9]+)'
    form_ids.update(re.findall(pattern2, content))
    
    # Pattern 3: Generic 24-char hex ID that could be a form
    pattern3 = r'[0-9a-f]{24}'
    potential_ids = re.findall(pattern3, content)
    
    return form_ids


def scan_for_forms(data_dir: Path, account: Optional[str] = None) -> Dict[str, dict]:
    """
    Scan workspace for form references.
    Returns dict of form_id -> {sources: [], first_seen: date}
    """
    forms = {}
    
    # Scan directories
    scan_dirs = [
        data_dir / "incoming",
        data_dir / "archive",
    ]
    
    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        
        for item in scan_dir.iterdir():
            if item.is_dir():
                # Check if directory name contains account info
                dir_account = None
                if account and account in item.name:
                    dir_account = account
                elif "_" in item.name:
                    parts = item.name.split("_")
                    if len(parts) >= 2:
                        dir_account = parts[1]  # e.g., 2025-09-15_ctiis_uid2817
                
                # Skip if we're filtering by account and this doesn't match
                if account and dir_account != account:
                    continue
                
                # Extract date from directory name
                dir_date = None
                if "_" in item.name:
                    date_part = item.name.split("_")[0]
                    try:
                        dir_date = datetime.strptime(date_part, "%Y-%m-%d")
                    except ValueError:
                        pass
                
                # Scan files in directory
                for file in item.iterdir():
                    if file.suffix in ['.html', '.txt', '.json', '.eml']:
                        ids = extract_form_ids_from_file(file)
                        for form_id in ids:
                            if form_id not in forms:
                                forms[form_id] = {
                                    "sources": [],
                                    "first_seen": dir_date.isoformat() if dir_date else None,
                                    "accounts": set()
                                }
                            forms[form_id]["sources"].append(str(file.relative_to(data_dir)))
                            if dir_account:
                                forms[form_id]["accounts"].add(dir_account)
    
    # Convert sets to lists for JSON serialization
    for form_id in forms:
        forms[form_id]["accounts"] = list(forms[form_id]["accounts"])
    
    return forms


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


def get_form_answers(form_id: str, token: str, page_size: int = 1) -> Optional[dict]:
    """Get form answers with pagination info."""
    url = f"{FORMS_API}/surveys/{form_id}/answers"
    headers = {"Authorization": f"OAuth {token}"}
    params = {"page_size": page_size}
    
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        return response.json()
    elif response.status_code == 404:
        return None
    elif response.status_code == 403:
        return {"error": "no_access"}
    else:
        raise RuntimeError(f"Failed to get answers: {response.status_code}")


def get_monthly_totals(form_id: str, token: str) -> Dict[str, int]:
    """
    Get response totals grouped by month.
    Returns {YYYY-MM: count}
    """
    monthly = {}
    
    # Fetch first batch to get total count
    data = get_form_answers(form_id, token, page_size=100)
    if not data or "error" in data:
        return monthly
    
    answers = data.get("answers", [])
    
    for answer in answers:
        created = answer.get("created", "")
        if created:
            # Parse ISO timestamp
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                month_key = dt.strftime("%Y-%m")
                monthly[month_key] = monthly.get(month_key, 0) + 1
            except ValueError:
                pass
    
    # If there are more pages, we just note that we have partial data
    # Full pagination would require multiple API calls
    next_page = data.get("next")
    total_count = data.get("count", len(answers))
    
    return {
        "monthly": monthly,
        "total_responses": total_count,
        "has_more": next_page is not None
    }


def load_registry(data_dir: Path) -> dict:
    """Load forms registry."""
    registry_path = data_dir / "forms" / "registry.json"
    if registry_path.exists():
        with open(registry_path) as f:
            return json.load(f)
    return {"forms": {}, "last_updated": None}


def save_registry(data_dir: Path, registry: dict):
    """Save forms registry."""
    registry_dir = data_dir / "forms"
    registry_dir.mkdir(parents=True, exist_ok=True)
    
    registry["last_updated"] = datetime.utcnow().isoformat() + "Z"
    
    registry_path = registry_dir / "registry.json"
    with open(registry_path, "w") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)


def discover_forms(
    account: str,
    data_dir: Path,
    token: str,
    scan_workspace: bool = True,
    update_registry: bool = True
) -> dict:
    """
    Main discovery function.
    
    Returns:
        dict with discovered forms and their stats
    """
    results = {
        "account": account,
        "discovered_at": datetime.utcnow().isoformat() + "Z",
        "forms": {}
    }
    
    # Load existing registry
    registry = load_registry(data_dir)
    
    # Scan workspace for form references
    if scan_workspace:
        print(f"Scanning workspace for form references...", file=sys.stderr)
        scanned_forms = scan_for_forms(data_dir, account)
        print(f"Found {len(scanned_forms)} potential form references", file=sys.stderr)
        
        # Merge with registry
        for form_id, info in scanned_forms.items():
            if form_id not in registry["forms"]:
                registry["forms"][form_id] = {
                    "discovered_from": "scan",
                    "first_seen": info.get("first_seen"),
                    "accounts": info.get("accounts", [])
                }
    
    # Query API for each form to get stats
    for form_id in registry["forms"]:
        try:
            form_info = get_form_info(form_id, token)
            if form_info:
                registry["forms"][form_id]["api_accessible"] = True
                registry["forms"][form_id]["title"] = form_info.get("title", "Unknown")
                registry["forms"][form_id]["status"] = form_info.get("status", "unknown")
                
                # Get monthly totals
                totals = get_monthly_totals(form_id, token)
                registry["forms"][form_id]["stats"] = totals
            else:
                registry["forms"][form_id]["api_accessible"] = False
                
        except Exception as e:
            registry["forms"][form_id]["error"] = str(e)
    
    # Save updated registry
    if update_registry:
        save_registry(data_dir, registry)
    
    results["forms"] = registry["forms"]
    results["registry_path"] = str(data_dir / "forms" / "registry.json")
    
    return results


def print_summary(results: dict):
    """Print formatted summary of discovered forms."""
    print(f"\n{'='*60}")
    print(f"Yandex Forms Discovery Results")
    print(f"Account: {results['account']}")
    print(f"{'='*60}\n")
    
    forms = results.get("forms", {})
    accessible = [f for f, d in forms.items() if d.get("api_accessible")]
    inaccessible = [f for f, d in forms.items() if not d.get("api_accessible")]
    
    print(f"Total forms in registry: {len(forms)}")
    print(f"API accessible: {len(accessible)}")
    print(f"Not accessible: {len(inaccessible)}")
    print()
    
    if accessible:
        print("Accessible Forms with Response Totals:")
        print("-" * 60)
        
        for form_id in sorted(accessible):
            data = forms[form_id]
            title = data.get("title", "Unknown")
            stats = data.get("stats", {})
            total = stats.get("total_responses", 0)
            monthly = stats.get("monthly", {})
            
            print(f"\n📋 {title}")
            print(f"   ID: {form_id}")
            print(f"   Total responses: {total}")
            
            if monthly:
                print(f"   Monthly breakdown:")
                for month in sorted(monthly.keys(), reverse=True):
                    print(f"      {month}: {monthly[month]} responses")
            
            if stats.get("has_more"):
                print(f"   ⚠️  More pages available (showing first 100)")


def main():
    parser = argparse.ArgumentParser(
        description="Discover Yandex Forms and get response statistics"
    )
    parser.add_argument(
        "--account",
        required=True,
        help="Account name (e.g., ctiis)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file for results (JSON)"
    )
    parser.add_argument(
        "--no-scan",
        action="store_true",
        help="Skip workspace scan, use existing registry only"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of formatted text"
    )
    
    args = parser.parse_args()
    
    try:
        runtime = load_runtime_context(__file__)
        data_dir = runtime.data_dir
        token = resolve_token(
            account=args.account,
            skill="forms",
            data_dir=data_dir,
            config=runtime.config,
            required_scopes=["forms:read"],
        ).token
        
        results = discover_forms(
            account=args.account,
            data_dir=data_dir,
            token=token,
            scan_workspace=not args.no_scan,
            update_registry=True
        )
        
        if args.json or args.output:
            if args.output:
                with open(args.output, "w") as f:
                    json.dump(results, f, indent=2, ensure_ascii=False)
                print(f"Saved to {args.output}")
            else:
                print(json.dumps(results, indent=2, ensure_ascii=False))
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
