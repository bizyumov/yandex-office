#!/usr/bin/env python3
"""
Add comment to an issue.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tracker_client import load_tracker_client, TrackerError


def main():
    parser = argparse.ArgumentParser(description="Add comment to Yandex Tracker issue")
    parser.add_argument("--account", required=True, help="Account name")
    parser.add_argument("--issue", required=True, help="Issue key")
    parser.add_argument("--text", required=True, help="Comment text")
    parser.add_argument("--summon", help="Comma-separated logins to mention")
    parser.add_argument("--no-follow", action="store_true", 
                        help="Don't add self to followers")
    parser.add_argument("--output", help="Output JSON file")
    parser.add_argument("--config", help="Path to config.json")
    
    args = parser.parse_args()
    
    try:
        client = load_tracker_client(args.account, args.config)
        
        summon = args.summon.split(",") if args.summon else None
        
        comment = client.add_comment(
            issue_key=args.issue,
            text=args.text,
            summon=summon,
            add_to_followers=not args.no_follow
        )
        
        if args.output:
            with open(args.output, "w") as f:
                json.dump(comment, f, ensure_ascii=False, indent=2)
        
        print(f"✅ Comment added to {args.issue}")
        
    except TrackerError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
