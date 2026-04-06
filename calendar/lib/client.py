"""CalDAV client wrapper for Yandex Calendar."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

import caldav
from icalendar import Calendar as iCalendar

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.auth import resolve_token
from common.config import load_runtime_context


class YandexCalendarClient:
    """Client for accessing Yandex Calendar via CalDAV."""

    CALDAV_URL = "https://caldav.yandex.ru"

    def __init__(
        self,
        account: str,
        data_dir: str | None = None,
        required_scopes: list[str] | None = None,
    ):
        self.account = account
        self.runtime = load_runtime_context(
            __file__,
            data_dir_override=data_dir,
            require_agent_config=True,
            require_external_data_dir=True,
        )
        self.data_dir = Path(data_dir).resolve() if data_dir else self.runtime.data_dir
        self.required_scopes = required_scopes or ["calendar"]
        self.email, self.token = self._load_credentials()
        self.client = None
        self.principal = None

    def _load_credentials(self) -> tuple[str | None, str]:
        token_info = resolve_token(
            account=self.account,
            skill="calendar",
            data_dir=self.data_dir,
            config=self.runtime.config,
            required_scopes=self.required_scopes,
        )
        return token_info.email, token_info.token

    def connect(self):
        """Establish CalDAV connection."""
        self.client = caldav.DAVClient(
            url=self.CALDAV_URL,
            username=self.email,
            password=self.token,
        )
        self.principal = self.client.principal()
        return self

    def get_calendars(self):
        """Get list of available calendars."""
        if not self.principal:
            self.connect()
        return self.principal.calendars()

    def find_calendar(self, name: str | None = None):
        """Find a calendar by name, or return default."""
        calendars = self.get_calendars()
        if not name:
            return calendars[0] if calendars else None

        for cal in calendars:
            if cal.name == name:
                return cal
        return None

    def list_events(
        self,
        calendar_name: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ):
        """List events in a date range."""
        if not self.principal:
            self.connect()

        calendar = self.find_calendar(calendar_name)
        if not calendar:
            available = [c.name for c in self.get_calendars()]
            raise ValueError(f"Calendar '{calendar_name}' not found. Available: {available}")

        if start is None:
            start = datetime.now()
        if end is None:
            end = start + timedelta(days=1)

        events = []
        for event in calendar.date_search(start=start, end=end):
            events.append(self._parse_event(event))

        return sorted(events, key=lambda e: e["start"])

    def _parse_event(self, event) -> dict:
        """Parse a caldav event into a dictionary."""
        ical = iCalendar.from_ical(event.data)

        for component in ical.walk("VEVENT"):
            result = {
                "uid": str(component.get("uid", "")),
                "summary": str(component.get("summary", "")),
                "start": component.get("dtstart").dt if component.get("dtstart") else None,
                "end": component.get("dtend").dt if component.get("dtend") else None,
                "location": str(component.get("location", "")),
                "description": str(component.get("description", "")),
                "is_recurring": component.get("rrule") is not None,
            }

            attendees = component.get("attendee", [])
            if not isinstance(attendees, list):
                attendees = [attendees]

            parsed_attendees = []
            for attendee in attendees:
                # Parse attendee object to extract email and CN (common name)
                email = str(attendee)
                if email.startswith("mailto:"):
                    email = email[7:]  # Remove mailto: prefix

                attendee_data = {"email": email}

                # Extract CN parameter (full name) if available
                if hasattr(attendee, "params"):
                    cn = attendee.params.get("CN")
                    if cn:
                        attendee_data["cn"] = str(cn)

                    # Extract RSVP status
                    partstat = attendee.params.get("PARTSTAT")
                    if partstat:
                        attendee_data["partstat"] = str(partstat)

                    # Extract attendee type (INDIVIDUAL, GROUP, etc.)
                    cutype = attendee.params.get("CUTYPE")
                    if cutype:
                        attendee_data["cutype"] = str(cutype)

                    # Extract role (REQ-PARTICIPANT, OPT-PARTICIPANT, etc.)
                    role = attendee.params.get("ROLE")
                    if role:
                        attendee_data["role"] = str(role)

                parsed_attendees.append(attendee_data)

            result["attendees"] = parsed_attendees

            return result

        return {}
