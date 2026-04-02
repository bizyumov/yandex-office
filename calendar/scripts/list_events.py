#!/usr/bin/env python3
"""List calendar events for a specific date."""
import sys
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from client import YandexCalendarClient


def parse_date(date_str: str) -> datetime:
    """Parse various date formats."""
    date_str = date_str.lower().strip()
    
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    if date_str in ('today', 'сегодня'):
        return today
    elif date_str in ('tomorrow', 'завтра'):
        return today + timedelta(days=1)
    elif date_str in ('yesterday', 'вчера'):
        return today - timedelta(days=1)
    else:
        # Try ISO format
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            # Try DD.MM.YYYY
            try:
                return datetime.strptime(date_str, "%d.%m.%Y")
            except ValueError:
                raise ValueError(f"Cannot parse date: {date_str}")


def format_event(event: dict, index: int, show_attendees: bool = False) -> str:
    """Format a single event for display."""
    lines = [f"{index}. {event['summary']}"]

    # Time formatting
    start = event['start']
    end = event['end']

    if isinstance(start, datetime):
        time_str = f"{start.strftime('%H:%M')}"
        if end:
            time_str += f" – {end.strftime('%H:%M')}"
        lines.append(f"   • Time: {time_str}")

    if event.get('location'):
        lines.append(f"   • Location: {event['location']}")

    if event.get('is_recurring'):
        lines.append(f"   • 🔁 Recurring")

    if event.get('attendees'):
        if show_attendees:
            lines.append(f"   • Attendees ({len(event['attendees'])}):")
            for attendee in event['attendees']:
                if isinstance(attendee, str):
                    # Legacy format: simple email string
                    if attendee.startswith('mailto:'):
                        email = attendee[7:]  # Remove "mailto:" prefix
                    else:
                        email = attendee
                    lines.append(f"     • {email}")
                elif isinstance(attendee, dict):
                    # Structured attendee object with params
                    email = attendee.get('email', 'N/A')
                    name = attendee.get('cn', '')
                    status = attendee.get('partstat', '')
                    status_icon = ''
                    if status == 'ACCEPTED':
                        status_icon = '✅'
                    elif status == 'DECLINED':
                        status_icon = '❌'
                    elif status == 'TENTATIVE':
                        status_icon = '❓'

                    if name:
                        lines.append(f"     {status_icon} {name} <{email}>")
                    else:
                        lines.append(f"     {status_icon} {email}")
        else:
            lines.append(f"   • Attendees: {len(event['attendees'])}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="List Yandex Calendar events")
    parser.add_argument('--account', '-a', required=True, help='Account name (e.g., ctiis, bdi)')
    parser.add_argument('--date', '-d', default='today', help='Date to query (today, tomorrow, YYYY-MM-DD, DD.MM.YYYY)')
    parser.add_argument('--calendar', '-c', help='Calendar name (default: first available)')
    parser.add_argument('--json', '-j', action='store_true', help='Output as JSON')
    parser.add_argument('--show-attendees', action='store_true', help='Show full list of attendees')
    parser.add_argument('--data-dir', help='Path to data directory with auth tokens')
    
    args = parser.parse_args()
    
    try:
        # Parse date
        start_date = parse_date(args.date)
        end_date = start_date + timedelta(days=1)
        
        # Create client and fetch events
        client = YandexCalendarClient(
            args.account,
            data_dir=args.data_dir,
            required_scopes=["calendar"],
        )
        events = client.list_events(
            calendar_name=args.calendar,
            start=start_date,
            end=end_date
        )
        
        if args.json:
            output = {
                "date": start_date.strftime("%Y-%m-%d"),
                "account": args.account,
                "total_events": len(events),
                "events": events
            }
            print(json.dumps(output, indent=2, default=str))
        else:
            date_display = start_date.strftime("%A, %d %B %Y")
            print(f"📅 {args.account} — {date_display}")
            print("─" * 40)
            
            if not events:
                print("\n✅ No events scheduled")
            else:
                print(f"\n{len(events)} event(s):\n")
                for i, event in enumerate(events, 1):
                    print(format_event(event, i, show_attendees=args.show_attendees))
                    print()
        
        return 0
        
    except Exception as e:
        error_output = {
            "error": str(e),
            "type": type(e).__name__
        }
        if args.json:
            print(json.dumps(error_output))
        else:
            print(f"❌ Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
