#!/usr/bin/env python3
"""
List available queues.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tracker_client import load_tracker_client, TrackerError


def main():
    parser = argparse.ArgumentParser(description="List Yandex Tracker queues")
    parser.add_argument("--account", required=True, help="Account name")
    parser.add_argument("--output", help="Output JSON file")
    parser.add_argument("--config", help="Path to config.json")
    
    args = parser.parse_args()
    
    try:
        client = load_tracker_client(args.account, args.config)
        
        queues = client.get_queues()
        
        if args.output:
            with open(args.output, "w") as f:
                json.dump(queues, f, ensure_ascii=False, indent=2)
        
        print(f"📋 Available Queues ({len(queues)}):")
        print()
        
        for queue in queues:
            key = queue.get("key", "N/A")
            name = queue.get("name", "Unnamed")
            issues_count = queue.get("issuesCount", "?")
            
            print(f"  {key}: {name} ({issues_count} issues)")
        
    except TrackerError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
