#!/usr/bin/env python3
"""
Search issues in Yandex Tracker.
"""

import argparse
import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from tracker_client import load_tracker_client, TrackerError


def format_issue(issue: dict) -> str:
    """Format single issue for display."""
    key = issue.get("key", "N/A")
    summary = issue.get("summary", "No title")
    
    status_obj = issue.get("status", {})
    status = status_obj.get("display", "Unknown")
    status_key = status_obj.get("key", "")
    
    # Emoji for common statuses
    status_emoji = {
        "open": "🔴",
        "in_progress": "🟡",
        "resolved": "🟢",
        "closed": "⚫",
    }.get(status_key, "⚪")
    
    assignee_obj = issue.get("assignee", {})
    assignee = assignee_obj.get("display", "Unassigned") if assignee_obj else "Unassigned"
    
    priority_obj = issue.get("priority", {})
    priority = priority_obj.get("display", "Normal")
    
    updated = issue.get("updatedAt", "")[:16].replace("T", " ") if issue.get("updatedAt") else ""
    deadline = issue.get("dueDate", "")
    
    lines = [
        f"📋 {key}: {summary}",
        f"   Status: {status_emoji} {status}",
        f"   Assignee: {assignee}",
        f"   Priority: {priority}",
    ]
    
    if deadline:
        lines.append(f"   Deadline: {deadline}")
    if updated:
        lines.append(f"   Updated: {updated}")
    
    # Add link
    lines.append(f"   Link: https://tracker.yandex.ru/{key}")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Search Yandex Tracker issues")
    parser.add_argument("--account", required=True, help="Account name")
    parser.add_argument("--query", help="Search query (Tracker query language)")
    parser.add_argument("--filter", help="JSON filter object")
    parser.add_argument("--queue", help="Filter by queue key")
    parser.add_argument("--assignee", help="Filter by assignee")
    parser.add_argument("--status", help="Filter by status")
    parser.add_argument("--limit", type=int, default=50, help="Max results")
    parser.add_argument("--output", help="Output JSON file")
    parser.add_argument("--config", help="Path to config.json")
    
    args = parser.parse_args()
    
    try:
        client = load_tracker_client(args.account, args.config)
        
        # Build filter if individual params provided
        filter_obj = None
        if args.filter:
            filter_obj = json.loads(args.filter)
        elif args.queue or args.assignee or args.status:
            filter_obj = {}
            if args.queue:
                filter_obj["queue"] = args.queue
            if args.assignee:
                filter_obj["assignee"] = args.assignee
            if args.status:
                filter_obj["status"] = args.status
        
        # Determine search method
        if args.query:
            issues = client.search_issues(query=args.query, per_page=args.limit)
        elif filter_obj:
            issues = client.search_issues(filter_obj=filter_obj, per_page=args.limit)
        elif args.queue:
            issues = client.search_issues(queue=args.queue, per_page=args.limit)
        else:
            print("Error: One of --query, --filter, or --queue required", file=sys.stderr)
            sys.exit(1)
        
        # Output
        if args.output:
            with open(args.output, "w") as f:
                json.dump(issues, f, ensure_ascii=False, indent=2)
            print(f"Saved {len(issues)} issues to {args.output}")
        else:
            print("=" * 60)
            print(f"Yandex Tracker Search Results")
            print(f"Account: {args.account}")
            print("=" * 60)
            print()
            print(f"Found {len(issues)} issues:")
            print()
            
            for issue in issues:
                print(format_issue(issue))
                print("-" * 60)
    
    except TrackerError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in filter: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
