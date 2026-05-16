#!/usr/bin/env python3
"""Create a new calendar event with a real Telemost conference."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
CALENDAR_LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
DISK_SCRIPT_DIR = ROOT_DIR / "disk" / "scripts"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(CALENDAR_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(CALENDAR_LIB_DIR))
if str(DISK_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(DISK_SCRIPT_DIR))

from client import YandexCalendarClient
from common.api import YandexApiError
from download import YandexDisk
from telemost.lib.client import TelemostError, YandexTelemostClient


DEFAULT_ATTACHMENT_DIR = "disk:/yandex-office Calendar Attachments"


def _escape_ical_text(value: str) -> str:
    """Escape text according to the iCalendar TEXT value rules."""

    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def _build_attendee_lines(attendees: list[str]) -> list[str]:
    """Build VEVENT ATTENDEE properties for the comma-separated CLI emails."""

    return [
        (
            "ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;"
            f"PARTSTAT=NEEDS-ACTION:mailto:{email}"
        )
        for email in attendees
    ]


def _upload_attachment(
    *,
    account: str,
    data_dir: str | None,
    local_path: str,
    remote_dir: str,
) -> dict[str, object]:
    """Upload a local file to Disk and publish a URL suitable for ATTACH.

    GitHub issue #28 documents that Yandex Calendar does not expose CalDAV
    managed attachments.  The standards-compatible path we can exercise with
    OAuth today is: upload the file to Disk, publish it, then add an
    `ATTACH;VALUE=URI` property to the VEVENT.
    """

    local_file = Path(local_path).expanduser().resolve()
    remote_path = f"{remote_dir.rstrip('/')}/{uuid.uuid4()}_{local_file.name}"
    disk = YandexDisk(
        account=account,
        data_dir=data_dir,
    )
    upload = disk.upload_and_publish(
        local_file,
        remote_path,
        overwrite=True,
        create_parents=True,
    )
    public_url = str(upload.get("public_url") or "").strip()
    if not public_url:
        raise RuntimeError(f"Disk upload did not return public_url for {local_file}")
    mime_type = upload.get("mime_type") or mimetypes.guess_type(local_file.name)[0]
    return {
        "fileName": local_file.name,
        "url": public_url,
        "size": upload.get("size", local_file.stat().st_size),
        "mime_type": mime_type or "application/octet-stream",
        "disk_path": upload.get("path") or remote_path,
    }


def _build_attachment_lines(attachments: list[dict[str, object]]) -> list[str]:
    """Build VEVENT ATTACH URI properties from uploaded Disk resources."""

    lines: list[str] = []
    for attachment in attachments:
        mime_type = str(attachment.get("mime_type") or "application/octet-stream")
        url = str(attachment.get("url") or "").strip()
        if url:
            lines.append(f"ATTACH;FMTTYPE={mime_type};VALUE=URI:{url}")
    return lines


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
    attachments: list[str] | None = None,
    attachment_remote_dir: str = DEFAULT_ATTACHMENT_DIR,
) -> dict[str, object]:
    """Create a Calendar event with a real Telemost conference.

    If attachments are provided, the files are uploaded to Disk and linked from
    the VEVENT with `ATTACH;VALUE=URI`.  This is intentionally separate from
    Yandex web Calendar's internal attachment API described in issue #28.
    """

    calendar_client = YandexCalendarClient(
        account,
        data_dir=data_dir,
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
    uploaded_attachments = [
        _upload_attachment(
            account=account,
            data_dir=data_dir,
            local_path=attachment,
            remote_dir=attachment_remote_dir,
        )
        for attachment in attachments or []
    ]

    start = datetime.fromisoformat(start_str)
    end = start + timedelta(minutes=duration_minutes)
    calendar = calendar_client.find_calendar()

    uid = str(uuid.uuid4())
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dtstart = start.strftime("%Y%m%dT%H%M%S")
    dtend = end.strftime("%Y%m%dT%H%M%S")
    attendee_lines = _build_attendee_lines(attendees)
    method = "REQUEST" if attendees else "PUBLISH"
    organizer_line = (
        f"ORGANIZER;CN={calendar_client.account if hasattr(calendar_client, 'account') else account}:"
        f"mailto:{calendar_client.email}"
    )
    attachment_lines = _build_attachment_lines(uploaded_attachments)
    attachment_description = "".join(
        f"\\nAttachment: {item['fileName']} — {item['url']}"
        for item in uploaded_attachments
    )
    description = _escape_ical_text(
        f"Встреча в Телемосте\nСсылка: {telemost_link}{attachment_description}"
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
SUMMARY:{_escape_ical_text(summary)}
LOCATION:{telemost_link}
DESCRIPTION:{description}
{organizer_line}
SEQUENCE:0
STATUS:CONFIRMED
{chr(10).join(attendee_lines)}
{chr(10).join(attachment_lines)}
END:VEVENT
END:VCALENDAR"""

    event_url = f"{calendar.url}{uid}.ics"
    # Keep Calendar event creation on the Calendar client's decorated method;
    # direct requests.put(auth=(email, token)) bypasses GH41 good_at/bad_at.
    try:
        calendar_client.put_event(
            event_url=event_url,
            ical_data=ical_data,
        )
    except YandexApiError as exc:
        return {
            "success": False,
            "error": str(exc),
            "status_code": exc.status_code,
            "provider_error": exc.provider_error,
            "response": exc.payload,
            "telemost": conference,
        }

    return {
        "success": True,
        "uid": uid,
        "event_url": event_url,
        "summary": summary,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "telemost_link": telemost_link,
        "telemost": conference,
        "attendees": attendees,
        "attachments": uploaded_attachments,
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
        "--attachment",
        action="append",
        default=[],
        help="Local file to upload to Disk and attach to the event as an ATTACH URI",
    )
    parser.add_argument(
        "--attachment-remote-dir",
        default=DEFAULT_ATTACHMENT_DIR,
        help=f"Disk directory for uploaded attachments (default: {DEFAULT_ATTACHMENT_DIR})",
    )
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
            attachments=args.attachment,
            attachment_remote_dir=args.attachment_remote_dir,
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
            if result["attachments"]:
                print("Вложения:")
                for attachment in result["attachments"]:
                    print(f"  - {attachment['fileName']}: {attachment['url']}")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))

        return 0 if result["success"] else 1
    except (TelemostError, ValueError) as exc:
        payload = exc.to_dict() if isinstance(exc, TelemostError) else {"error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
