#!/usr/bin/env python3
"""
Create a new issue in Yandex Tracker.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tracker_client import load_tracker_client, TrackerError


def main():
    parser = argparse.ArgumentParser(description="Create Yandex Tracker issue")
    parser.add_argument("--account", required=True, help="Account name")
    parser.add_argument("--queue", required=True, help="Queue key")
    parser.add_argument("--summary", required=True, help="Issue title")
    parser.add_argument("--description", help="Issue description")
    parser.add_argument("--type", default="task", help="Issue type (default: task)")
    parser.add_argument("--priority", choices=["critical", "high", "normal", "low"],
                        help="Priority")
    parser.add_argument("--assignee", help="Assignee login or me()")
    parser.add_argument("--followers", help="Comma-separated follower logins")
    parser.add_argument("--tags", help="Comma-separated tags")
    parser.add_argument("--due-date", help="Due date (YYYY-MM-DD)")
    parser.add_argument("--parent", help="Parent issue key")
    parser.add_argument("--output", help="Output JSON file")
    parser.add_argument("--config", help="Path to config.json")
    
    args = parser.parse_args()
    
    try:
        client = load_tracker_client(args.account, args.config)
        
        # Parse lists
        followers = args.followers.split(",") if args.followers else None
        tags = args.tags.split(",") if args.tags else None
        
        issue = client.create_issue(
            queue=args.queue,
            summary=args.summary,
            description=args.description,
            issue_type=args.type,
            priority=args.priority,
            assignee=args.assignee,
            followers=followers,
            tags=tags,
            due_date=args.due_date,
            parent=args.parent
        )
        
        key = issue.get("key", "N/A")
        
        if args.output:
            with open(args.output, "w") as f:
                json.dump(issue, f, ensure_ascii=False, indent=2)
        
        print(f"✅ Issue created: {key}")
        print(f"   Title: {issue.get('summary')}")
        print(f"   Link: https://tracker.yandex.ru/{key}")
        
    except TrackerError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
