#!/usr/bin/env python3
"""
Get Agile board details.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tracker_client import load_tracker_client, TrackerError


def format_board(board: dict) -> str:
    """Format board info."""
    lines = []
    
    name = board.get("name", "Unnamed")
    board_id = board.get("id", "N/A")
    
    lines.append(f"📋 Board: {name} (ID: {board_id})")
    lines.append("=" * 60)
    
    # Columns
    columns = board.get("columns", [])
    lines.append(f"\nColumns ({len(columns)}):")
    
    for col in columns:
        col_name = col.get("name", "Unknown")
        col_status = col.get("status", {}).get("display", "")
        
        # Count issues in column
        issues = col.get("issues", [])
        count = len(issues)
        
        lines.append(f"  \n📁 {col_name} [{col_status}] - {count} issues")
        
        # List issues
        for issue in issues[:5]:  # Show first 5
            key = issue.get("key", "N/A")
            summary = issue.get("summary", "No title")[:40]
            lines.append(f"    • {key}: {summary}")
        
        if len(issues) > 5:
            lines.append(f"    ... and {len(issues) - 5} more")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Get Yandex Tracker board")
    parser.add_argument("--account", required=True, help="Account name")
    parser.add_argument("--board", type=int, required=True, help="Board ID")
    parser.add_argument("--output", help="Output JSON file")
    
    args = parser.parse_args()
    
    try:
        client = load_tracker_client(args.account)
        
        board = client.get_board(args.board)
        
        if args.output:
            with open(args.output, "w") as f:
                json.dump(board, f, ensure_ascii=False, indent=2)
        
        print(format_board(board))
        
    except TrackerError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
