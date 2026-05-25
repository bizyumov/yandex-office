#!/usr/bin/env python3
"""Create a new calendar event with a real Telemost conference."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.api import YandexApiError
from disk.scripts.download import YandexDisk
from telemost.lib.client import TelemostError, YandexTelemostClient
from calendars.lib.client import YandexCalendarClient
from common.config import find_skill_root, load_agent_config, load_global_config, resolve_data_dir


DEFAULT_ATTACHMENT_DIR = "disk:/yandex-office Calendar Attachments"
UTC_OFFSET_RE = re.compile(r"^([+-])(\d{2}):(\d{2})$")
TIME_CONTEXT_KEYS = ("timezone", "utc_offset")


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


def _parse_utc_offset(value: str) -> tuple[timezone, str]:
    """Parse a CLI UTC offset into a fixed-offset tzinfo and normalized label."""

    raw = value.strip()
    if raw == "Z":
        return timezone.utc, "Z"
    match = UTC_OFFSET_RE.match(raw)
    if not match:
        raise ValueError("--utc-offset must be Z, +HH:MM, or -HH:MM")
    sign, hours_raw, minutes_raw = match.groups()
    hours = int(hours_raw)
    minutes = int(minutes_raw)
    if hours > 23 or minutes > 59:
        raise ValueError("--utc-offset must be Z, +HH:MM, or -HH:MM")
    delta = timedelta(hours=hours, minutes=minutes)
    if sign == "-":
        delta = -delta
    return timezone(delta), raw


def _format_utc_offset(delta: timedelta | None) -> str:
    if delta is None:
        raise ValueError("Timezone has no UTC offset at the event start")
    total_seconds = int(delta.total_seconds())
    if total_seconds == 0:
        return "Z"
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def _calendar_config_section(config: dict[str, object], *, source: str) -> dict[str, object]:
    raw = config.get("calendar")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{source} calendar config must be an object")
    return raw


def _config_string(section: dict[str, object], key: str, *, source: str) -> str | None:
    if key not in section:
        return None
    raw = section.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{source} calendar.{key} must be a non-empty string")
    return raw.strip()


def _reject_global_calendar_time_preference() -> None:
    skill_root = find_skill_root(__file__)
    global_config_path, global_config = load_global_config(skill_root)
    section = _calendar_config_section(global_config, source=global_config_path.name)
    forbidden = [key for key in TIME_CONTEXT_KEYS if key in section]
    if forbidden:
        fields = ", ".join(f"calendar.{key}" for key in forbidden)
        raise ValueError(
            f"{global_config_path.name} must not define {fields}; "
            "set Calendar time preference in config.agent.json"
        )


def _agent_calendar_time_preference(data_dir: str | None) -> tuple[str | None, str | None]:
    resolved_data_dir = resolve_data_dir(data_dir_override=data_dir)
    _agent_config_path, agent_config = load_agent_config(resolved_data_dir, required=False)
    section = _calendar_config_section(agent_config, source="config.agent.json")
    return (
        _config_string(section, "timezone", source="config.agent.json"),
        _config_string(section, "utc_offset", source="config.agent.json"),
    )


def _validate_matching_time_context(
    *,
    start_str: str,
    timezone_name: str,
    utc_offset: str,
    source: str,
) -> None:
    try:
        context_tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {timezone_name}") from exc
    _offset_tz, normalized_offset = _parse_utc_offset(utc_offset)
    localized_start = _localize_start(start_str, context_tz)
    timezone_offset = _format_utc_offset(localized_start.utcoffset())
    if timezone_offset != normalized_offset:
        raise ValueError(
            f"{source} timezone and utc_offset conflict: {timezone_name} is "
            f"{timezone_offset} at {start_str}, not {normalized_offset}"
        )


def _effective_time_context(
    *,
    start_str: str,
    data_dir: str | None,
    timezone_name: str | None,
    utc_offset: str | None,
) -> tuple[str | None, str | None]:
    _reject_global_calendar_time_preference()
    cli_timezone = timezone_name.strip() if isinstance(timezone_name, str) and timezone_name.strip() else None
    cli_utc_offset = utc_offset.strip() if isinstance(utc_offset, str) and utc_offset.strip() else None
    if cli_timezone or cli_utc_offset:
        if cli_timezone and cli_utc_offset:
            _validate_matching_time_context(
                start_str=start_str,
                timezone_name=cli_timezone,
                utc_offset=cli_utc_offset,
                source="CLI",
            )
        return cli_timezone, cli_utc_offset

    config_timezone, config_utc_offset = _agent_calendar_time_preference(data_dir)
    if config_timezone and config_utc_offset:
        _validate_matching_time_context(
            start_str=start_str,
            timezone_name=config_timezone,
            utc_offset=config_utc_offset,
            source="config.agent.json",
        )
    return config_timezone, config_utc_offset


def _resolve_scheduling_context(
    start_str: str,
    timezone_name: str | None,
    utc_offset: str | None,
) -> tuple[tzinfo, str | None, str | None]:
    """Resolve the explicit user time context required for event creation."""

    if not timezone_name and not utc_offset:
        raise ValueError("Provide exactly one of --timezone or --utc-offset")
    if timezone_name:
        try:
            return ZoneInfo(timezone_name), timezone_name, None
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown timezone: {timezone_name}") from exc
    offset_tz, normalized_offset = _parse_utc_offset(utc_offset or "")
    return offset_tz, None, normalized_offset


def _localize_start(start_str: str, context_tz: tzinfo) -> datetime:
    start = datetime.fromisoformat(start_str)
    if start.tzinfo is None:
        return start.replace(tzinfo=context_tz)
    return start.astimezone(context_tz)


def _ical_datetime_line(name: str, value: datetime, timezone_name: str | None) -> str:
    if timezone_name:
        return f"{name};TZID={timezone_name}:{value.strftime('%Y%m%dT%H%M%S')}"
    return f"{name}:{value.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def create_telemost_event(
    account: str,
    summary: str,
    start_str: str,
    duration_minutes: int,
    attendees: list[str],
    data_dir: str | None = None,
    timezone_name: str | None = None,
    utc_offset: str | None = None,
    event_uid: str | None = None,
    telemost_link: str | None = None,
    telemost_conference_id: str | None = None,
    telemost_access_level: str | None = None,
    telemost_waiting_room: str | None = None,
    telemost_cohosts: list[str] | None = None,
    telemost_settings_supplied: bool = False,
    telemost_cohosts_supplied: bool = False,
    attachments: list[str] | None = None,
    attachment_remote_dir: str = DEFAULT_ATTACHMENT_DIR,
) -> dict[str, object]:
    """Create a Calendar event with a real Telemost conference.

    If attachments are provided, the files are uploaded to Disk and linked from
    the VEVENT with `ATTACH;VALUE=URI`.  This is intentionally separate from
    Yandex web Calendar's internal attachment API described in issue #28.
    """

    effective_timezone, effective_utc_offset = _effective_time_context(
        start_str=start_str,
        data_dir=data_dir,
        timezone_name=timezone_name,
        utc_offset=utc_offset,
    )
    context_tz, selected_timezone, selected_utc_offset = _resolve_scheduling_context(
        start_str,
        effective_timezone,
        effective_utc_offset,
    )
    settings_requested = (
        telemost_settings_supplied
        or telemost_access_level not in (None, "PUBLIC")
        or telemost_waiting_room not in (None, "PUBLIC")
        or bool(telemost_cohosts)
        or telemost_cohosts_supplied
    )
    if telemost_link and not telemost_conference_id and settings_requested:
        raise ValueError("Telemost settings require a conference id to update or a new conference to create")

    calendar_client = YandexCalendarClient(
        account,
        data_dir=data_dir,
    )
    calendar_client.connect()

    conference: dict[str, object] | None = None
    if telemost_conference_id:
        telemost_client = YandexTelemostClient(account, data_dir=data_dir)
        updated: dict[str, object] | None = None
        if settings_requested:
            update_kwargs: dict[str, object] = {}
            if telemost_access_level is not None:
                update_kwargs["access_level"] = telemost_access_level
            if telemost_waiting_room is not None:
                update_kwargs["waiting_room_level"] = telemost_waiting_room
            if telemost_cohosts_supplied or telemost_cohosts:
                update_kwargs["cohosts"] = telemost_cohosts or []
            if update_kwargs:
                updated = telemost_client.update_conference(telemost_conference_id, **update_kwargs)
        if telemost_link:
            conference = {"id": telemost_conference_id, "join_url": telemost_link}
            if updated:
                conference.update({key: value for key, value in updated.items() if value is not None})
            conference["join_url"] = telemost_link
        else:
            conference = telemost_client.get_conference(telemost_conference_id)
            if updated:
                conference.update({key: value for key, value in updated.items() if value is not None})
    elif telemost_link:
        conference = {"id": None, "join_url": telemost_link}
    else:
        telemost_client = YandexTelemostClient(account, data_dir=data_dir)
        conference = telemost_client.create_conference(
            access_level=telemost_access_level or "PUBLIC",
            waiting_room_level=telemost_waiting_room or "PUBLIC",
            cohosts=telemost_cohosts or [],
        )
    if not conference or not conference.get("join_url"):
        raise ValueError("Telemost link is missing")
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

    start_local = _localize_start(start_str, context_tz)
    end_local = start_local + timedelta(minutes=duration_minutes)
    calendar = calendar_client.find_calendar()

    uid = event_uid or str(uuid.uuid4())
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dtstart_line = _ical_datetime_line("DTSTART", start_local, selected_timezone)
    dtend_line = _ical_datetime_line("DTEND", end_local, selected_timezone)
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
{dtstart_line}
{dtend_line}
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

    result = {
        "success": True,
        "uid": uid,
        "event_url": event_url,
        "summary": summary,
        "start": start_local.isoformat(),
        "end": end_local.isoformat(),
        "telemost_link": telemost_link,
        "telemost": conference,
        "attendees": attendees,
        "attachments": uploaded_attachments,
    }
    if selected_timezone:
        result["timezone"] = selected_timezone
    else:
        result["utc_offset"] = selected_utc_offset
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Yandex Calendar event with Telemost")
    parser.add_argument("--account", "-a", required=True, help="Account name")
    parser.add_argument("--summary", "-s", required=True, help="Event title")
    parser.add_argument("--start", required=True, help="Start time (ISO format, e.g., 2026-03-04T15:00:00)")
    parser.add_argument("--duration", "-d", type=int, default=60, help="Duration in minutes")
    parser.add_argument("--attendees", help="Comma-separated email addresses")
    parser.add_argument("--data-dir", help="Path to data directory")
    parser.add_argument(
        "--timezone",
        help="IANA timezone for the user-provided start time; overrides config.agent.json",
    )
    parser.add_argument(
        "--utc-offset",
        help="UTC offset for the user-provided start time: Z, +HH:MM, or -HH:MM; overrides config.agent.json",
    )
    parser.add_argument("--event-uid", help="Reuse an existing calendar event UID instead of creating a new one")
    parser.add_argument("--telemost-link", help="Reuse an existing Telemost join URL instead of fetching/creating a conference")
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
    telemost_access_level = getattr(args, "telemost_access_level", None)
    telemost_waiting_room = getattr(args, "telemost_waiting_room", None)
    telemost_cohosts_supplied = hasattr(args, "telemost_cohosts")
    telemost_cohosts_raw = getattr(args, "telemost_cohosts", "")
    telemost_cohosts = [email.strip() for email in telemost_cohosts_raw.split(",") if email.strip()]
    telemost_settings_supplied = any(
        [
            hasattr(args, "telemost_access_level"),
            hasattr(args, "telemost_waiting_room"),
            telemost_cohosts_supplied,
        ]
    )

    try:
        result = create_telemost_event(
            args.account,
            args.summary,
            args.start,
            args.duration,
            attendees,
            data_dir=args.data_dir,
            timezone_name=args.timezone,
            utc_offset=args.utc_offset,
            event_uid=args.event_uid,
            telemost_link=args.telemost_link,
            telemost_conference_id=args.telemost_conference_id,
            telemost_access_level=telemost_access_level,
            telemost_waiting_room=telemost_waiting_room,
            telemost_cohosts=telemost_cohosts,
            telemost_settings_supplied=telemost_settings_supplied,
            telemost_cohosts_supplied=telemost_cohosts_supplied,
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
