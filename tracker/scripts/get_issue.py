#!/usr/bin/env python3
"""
Get issue details.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tracker_client import load_tracker_client, TrackerError


def format_issue_full(issue: dict) -> str:
    """Format issue with full details."""
    lines = []
    
    key = issue.get("key", "N/A")
    summary = issue.get("summary", "No title")
    lines.append(f"📋 {key}: {summary}")
    lines.append("=" * 60)
    
    # Status and priority
    status = issue.get("status", {}).get("display", "Unknown")
    priority = issue.get("priority", {}).get("display", "Normal")
    type_name = issue.get("type", {}).get("display", "Task")
    
    lines.append(f"Type: {type_name}")
    lines.append(f"Status: {status}")
    lines.append(f"Priority: {priority}")
    
    # People
    assignee = issue.get("assignee", {}).get("display", "Unassigned") if issue.get("assignee") else "Unassigned"
    author = issue.get("createdBy", {}).get("display", "Unknown")
    
    lines.append(f"Assignee: {assignee}")
    lines.append(f"Author: {author}")
    
    # Dates
    created = issue.get("createdAt", "")[:16].replace("T", " ") if issue.get("createdAt") else ""
    updated = issue.get("updatedAt", "")[:16].replace("T", " ") if issue.get("updatedAt") else ""
    deadline = issue.get("dueDate", "")
    
    lines.append(f"Created: {created}")
    lines.append(f"Updated: {updated}")
    if deadline:
        lines.append(f"Deadline: {deadline}")
    
    # Queue and project
    queue = issue.get("queue", {}).get("display", "Unknown")
    lines.append(f"Queue: {queue}")
    
    project = issue.get("project", {}).get("primary", {}).get("display", "")
    if project:
        lines.append(f"Project: {project}")
    
    # Tags
    tags = issue.get("tags", [])
    if tags:
        lines.append(f"Tags: {', '.join(tags)}")
    
    # Description
    description = issue.get("description", "")
    if description:
        lines.append("")
        lines.append("Description:")
        lines.append("-" * 40)
        # Strip HTML if present
        if description.startswith("<"):
            lines.append("[HTML content - view in Tracker]")
        else:
            lines.append(description[:500])
            if len(description) > 500:
                lines.append("...")
    
    # Comments
    comments = issue.get("comments", [])
    if comments:
        lines.append("")
        lines.append(f"Comments ({len(comments)}):")
        lines.append("-" * 40)
        for comment in comments[-3:]:  # Show last 3
            author = comment.get("createdBy", {}).get("display", "Unknown")
            text = comment.get("text", "")[:100]
            lines.append(f"  {author}: {text}...")
    
    lines.append("")
    lines.append(f"Link: https://tracker.yandex.ru/{key}")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Get Yandex Tracker issue details")
    parser.add_argument("--account", required=True, help="Account name")
    parser.add_argument("--issue", required=True, help="Issue key (e.g., PROJ-123)")
    parser.add_argument("--with-comments", action="store_true", help="Include comments")
    parser.add_argument("--with-transitions", action="store_true", help="Include transitions")
    parser.add_argument("--output", help="Output JSON file")
    parser.add_argument("--config", help="Path to config.json")
    
    args = parser.parse_args()
    
    try:
        client = load_tracker_client(args.account, args.config)
        
        expand = []
        if args.with_comments:
            expand.append("comments")
        if args.with_transitions:
            expand.append("transitions")
        
        issue = client.get_issue(args.issue, expand=expand if expand else None)
        
        if args.output:
            with open(args.output, "w") as f:
                json.dump(issue, f, ensure_ascii=False, indent=2)
        
        print(format_issue_full(issue))
        
    except TrackerError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
