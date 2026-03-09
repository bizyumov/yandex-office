#!/usr/bin/env python3
"""
Update issue fields or status.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tracker_client import load_tracker_client, TrackerError


def main():
    parser = argparse.ArgumentParser(description="Update Yandex Tracker issue")
    parser.add_argument("--account", required=True, help="Account name")
    parser.add_argument("--issue", required=True, help="Issue key")
    parser.add_argument("--summary", help="New title")
    parser.add_argument("--description", help="New description")
    parser.add_argument("--status", help="New status")
    parser.add_argument("--assignee", help="New assignee (login, me(), or empty())")
    parser.add_argument("--priority", choices=["critical", "high", "normal", "low"],
                        help="New priority")
    parser.add_argument("--resolution", help="Resolution when closing")
    parser.add_argument("--add-tags", help="Comma-separated tags to add")
    parser.add_argument("--remove-tags", help="Comma-separated tags to remove")
    parser.add_argument("--due-date", help="New due date (YYYY-MM-DD)")
    parser.add_argument("--follow", action="store_true", help="Add self to followers")
    parser.add_argument("--output", help="Output JSON file")
    parser.add_argument("--config", help="Path to config.json")
    
    args = parser.parse_args()
    
    try:
        client = load_tracker_client(args.account, args.config)
        
        # Build update fields
        add_tags = args.add_tags.split(",") if args.add_tags else None
        remove_tags = args.remove_tags.split(",") if args.remove_tags else None
        
        # Update issue fields
        issue = client.update_issue(
            issue_key=args.issue,
            summary=args.summary,
            description=args.description,
            priority=args.priority,
            assignee=args.assignee,
            due_date=args.due_date,
            add_tags=add_tags,
            remove_tags=remove_tags
        )
        
        # Handle status transition if requested
        if args.status:
            # Get available transitions
            issue_with_transitions = client.get_issue(args.issue, expand=["transitions"])
            transitions = issue_with_transitions.get("transitions", [])
            
            # Find matching transition
            transition_id = None
            for t in transitions:
                if t.get("display", "").lower() == args.status.lower() or \
                   t.get("id", "").lower() == args.status.lower():
                    transition_id = t.get("id")
                    break
            
            if transition_id:
                issue = client.transition_issue(
                    issue_key=args.issue,
                    transition_id=transition_id,
                    resolution=args.resolution
                )
            else:
                print(f"Warning: No transition found for status '{args.status}'", 
                      file=sys.stderr)
                print(f"Available transitions: {[t.get('display') for t in transitions]}",
                      file=sys.stderr)
        
        if args.output:
            with open(args.output, "w") as f:
                json.dump(issue, f, ensure_ascii=False, indent=2)
        
        print(f"✅ Issue {args.issue} updated")
        print(f"   Status: {issue.get('status', {}).get('display', 'Unknown')}")
        print(f"   Assignee: {issue.get('assignee', {}).get('display', 'Unassigned')}")
        
    except TrackerError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
