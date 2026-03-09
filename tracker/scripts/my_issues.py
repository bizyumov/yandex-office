#!/usr/bin/env python3
"""
List issues assigned to current user.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tracker_client import load_tracker_client, TrackerError


def format_issue_line(issue: dict) -> str:
    """Format issue as single line."""
    key = issue.get("key", "N/A")
    summary = issue.get("summary", "No title")[:50]
    
    status_obj = issue.get("status", {})
    status = status_obj.get("display", "?")
    
    priority_obj = issue.get("priority", {})
    priority = priority_obj.get("key", "normal")
    
    priority_mark = {
        "critical": "🔴",
        "high": "🟠",
        "normal": "⚪",
        "low": "⚫",
    }.get(priority, "⚪")
    
    deadline = issue.get("dueDate", "")
    deadline_str = f" (due: {deadline})" if deadline else ""
    
    return f"{priority_mark} {key}: {summary}{deadline_str} [{status}]"


def main():
    parser = argparse.ArgumentParser(description="List my Yandex Tracker issues")
    parser.add_argument("--account", required=True, help="Account name")
    parser.add_argument("--status", help="Filter by status (default: open)")
    parser.add_argument("--queue", help="Filter by queue")
    parser.add_argument("--priority", help="Filter by priority")
    parser.add_argument("--limit", type=int, default=20, help="Max results")
    parser.add_argument("--overdue", action="store_true", help="Show only overdue")
    parser.add_argument("--config", help="Path to config.json")
    
    args = parser.parse_args()
    
    try:
        client = load_tracker_client(args.account, args.config)
        
        # Build query
        conditions = ["Assignee: me()"]
        
        if args.overdue:
            conditions.append("Deadline: < today() Status: !closed")
        elif args.status:
            conditions.append(f"Status: {args.status}")
        else:
            conditions.append("Status: !closed")
        
        if args.queue:
            conditions.append(f"Queue: {args.queue}")
        
        if args.priority:
            conditions.append(f"Priority: {args.priority}")
        
        query = " AND ".join(conditions)
        
        issues = client.search_issues(query=query, per_page=args.limit)
        
        print(f"📋 My Issues ({len(issues)} found):")
        print()
        
        if not issues:
            print("No issues found.")
        else:
            for issue in issues:
                print(format_issue_line(issue))
        
    except TrackerError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
