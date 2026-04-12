#!/usr/bin/env python3
"""Create a new calendar event with a real Telemost conference."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import requests

ROOT_DIR = Path(__file__).resolve().parents[2]
CALENDAR_LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(CALENDAR_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(CALENDAR_LIB_DIR))

from client import YandexCalendarClient
from telemost.lib.client import TelemostError, YandexTelemostClient


def _build_attendee_lines(attendees: list[str]) -> list[str]:
    return [
        (
            "ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;"
            f"PARTSTAT=NEEDS-ACTION:mailto:{email}"
        )
        for email in attendees
    ]


def create_telemost_event(
    account: str,
    summary: str,
    start_str: str,
    duration_minutes: int,
    attendees: list[str],
    data_dir: str | None = None,
    telemost_conference_id: str | None = None,
    telemost_access_level: str | None = "PUBLIC",
    telemost_waiting_room: str | None = "PUBLIC",
    telemost_cohosts: list[str] | None = None,
) -> dict[str, object]:
    """Create an event with a real Telemost conference."""

    calendar_client = YandexCalendarClient(
        account,
        data_dir=data_dir,
        required_scopes=["calendar:all"],
    )
    calendar_client.connect()

    telemost_client = YandexTelemostClient(account, data_dir=data_dir)
    if telemost_conference_id:
        conference = telemost_client.get_conference(telemost_conference_id)
    else:
        conference = telemost_client.create_conference(
            access_level=telemost_access_level,
            waiting_room_level=telemost_waiting_room,
            cohosts=telemost_cohosts or [],
        )
    telemost_link = conference["join_url"]

    start = datetime.fromisoformat(start_str)
    if start.tzinfo is None:
        start_local = start.replace(tzinfo=ZoneInfo("Europe/Moscow"))
    else:
        start_local = start.astimezone(ZoneInfo("Europe/Moscow"))
    end_local = start_local + timedelta(minutes=duration_minutes)
    calendar = calendar_client.find_calendar()

    uid = str(uuid.uuid4())
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dtstart = start_local.strftime("%Y%m%dT%H%M%S")
    dtend = end_local.strftime("%Y%m%dT%H%M%S")
    attendee_lines = _build_attendee_lines(attendees)
    method = "REQUEST" if attendees else "PUBLISH"
    organizer_line = (
        f"ORGANIZER;CN={calendar_client.account if hasattr(calendar_client, 'account') else account}:"
        f"mailto:{calendar_client.email}"
    )

    ical_data = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Yandex Calendar//EN
CALSCALE:GREGORIAN
METHOD:{method}
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{dtstamp}
DTSTART;TZID=Europe/Moscow:{dtstart}
DTEND;TZID=Europe/Moscow:{dtend}
SUMMARY:{summary}
LOCATION:{telemost_link}
DESCRIPTION:Встреча в Телемосте\\nСсылка: {telemost_link}
{organizer_line}
SEQUENCE:0
STATUS:CONFIRMED
{chr(10).join(attendee_lines)}
END:VEVENT
END:VCALENDAR"""

    event_url = f"{calendar.url}{uid}.ics"
    response = requests.put(
        event_url,
        auth=(calendar_client.email, calendar_client.token),
        data=ical_data,
        headers={"Content-Type": "text/calendar; charset=utf-8"},
        timeout=30,
    )

    if response.status_code not in (201, 204):
        return {
            "success": False,
            "error": f"HTTP {response.status_code}",
            "response": response.text[:500],
            "telemost": conference,
        }

    return {
        "success": True,
        "uid": uid,
        "event_url": event_url,
        "summary": summary,
        "start": start_local.isoformat(),
        "end": end_local.isoformat(),
        "telemost_link": telemost_link,
        "telemost": conference,
        "attendees": attendees,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Yandex Calendar event with Telemost")
    parser.add_argument("--account", "-a", required=True, help="Account name")
    parser.add_argument("--summary", "-s", required=True, help="Event title")
    parser.add_argument("--start", required=True, help="Start time (ISO format, e.g., 2026-03-04T15:00:00)")
    parser.add_argument("--duration", "-d", type=int, default=60, help="Duration in minutes")
    parser.add_argument("--attendees", help="Comma-separated email addresses")
    parser.add_argument("--data-dir", help="Path to data directory")
    parser.add_argument("--telemost-conference-id", help="Use an existing Telemost conference instead of creating a new one")
    parser.add_argument(
        "--telemost-access-level",
        default=argparse.SUPPRESS,
        help="Telemost access level for a newly created conference (default: PUBLIC)",
    )
    parser.add_argument(
        "--telemost-waiting-room",
        default=argparse.SUPPRESS,
        help="Telemost waiting room level for a newly created conference (default: PUBLIC)",
    )
    parser.add_argument(
        "--telemost-cohosts",
        default=argparse.SUPPRESS,
        help="Comma-separated cohost emails for a newly created conference (default: none)",
    )
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    attendees = [email.strip() for email in (args.attendees or "").split(",") if email.strip()]
    telemost_access_level = getattr(args, "telemost_access_level", "PUBLIC")
    telemost_waiting_room = getattr(args, "telemost_waiting_room", "PUBLIC")
    telemost_cohosts_raw = getattr(args, "telemost_cohosts", None)
    telemost_cohosts = [email.strip() for email in (telemost_cohosts_raw or "").split(",") if email.strip()]

    if args.telemost_conference_id:
        conflicting = []
        if hasattr(args, "telemost_access_level"):
            conflicting.append("--telemost-access-level")
        if hasattr(args, "telemost_waiting_room"):
            conflicting.append("--telemost-waiting-room")
        if hasattr(args, "telemost_cohosts"):
            conflicting.append("--telemost-cohosts")
        if conflicting:
            print(
                json.dumps(
                    {
                        "error": "--telemost-conference-id cannot be combined with "
                        + ", ".join(conflicting)
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 1

    try:
        result = create_telemost_event(
            args.account,
            args.summary,
            args.start,
            args.duration,
            attendees,
            data_dir=args.data_dir,
            telemost_conference_id=args.telemost_conference_id,
            telemost_access_level=telemost_access_level,
            telemost_waiting_room=telemost_waiting_room,
            telemost_cohosts=telemost_cohosts,
        )

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif result["success"]:
            print("Встреча создана")
            print(result["summary"])
            print(f"{result['start']} – {result['end']}")
            print(result["telemost_link"])
            if result["attendees"]:
                print("Участники:")
                for attendee in result["attendees"]:
                    print(f"  - {attendee}")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))

        return 0 if result["success"] else 1
    except (TelemostError, ValueError) as exc:
        payload = exc.to_dict() if isinstance(exc, TelemostError) else {"error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
