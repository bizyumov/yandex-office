# Yandex Calendar / Календарь

## Overview

A CalDAV-based Calendar / Календарь skill for managing Yandex Calendar events, integrated with the Yandex skill ecosystem. Provides read/write access to calendars, meeting scheduling, and multi-user availability queries.

---

## API Discovery

### Endpoint
- **CalDAV URL**: `https://caldav.yandex.ru`
- **Protocol**: CalDAV (RFC 4791)
- **Authentication**: OAuth 2.0 token with `calendar` scope

### Authentication
```json
{
  "email": "user@yandex.ru",
  "token.calendar": "y0_..."
}
```

Token stored per-account at: `{data_dir}/auth/{account}.token`

### Account Structure
- Each user has a principal with multiple calendars
- Default calendars: "Мои события", "Не забыть"
- Calendar discovery via `principal.calendars()`

---

## Scenarios

### 1. Show Meetings for a Date

**User Request Examples:**
- "What meetings do I have tomorrow?"
- "Show my calendar for March 3rd"
- "Any meetings on Friday?"

**Requirements:**
- Accept natural language date parsing (today, tomorrow, next week, specific dates)
- Support filtering by calendar (optional)
- Return event details:
  - Title/summary
  - Start and end time (with timezone)
  - Calendar name
  - Location (if set)
  - Description (if set)
  - Attendees (if any)
  - Recurrence info (for recurring events)

**Output Format:**
```json
{
  "date": "2026-03-03",
  "account": "ctiis",
  "total_events": 3,
  "events": [
    {
      "uid": "event-uuid",
      "summary": "Сбер ЦФА",
      "calendar": "Мои события",
      "start": "2026-03-03T14:00:00+03:00",
      "end": "2026-03-03T15:00:00+03:00",
      "location": "Zoom",
      "description": "Quarterly review",
      "is_recurring": false,
      "attendees": ["user@yandex.ru", "colleague@yandex.ru"]
    }
  ]
}
```

**CLI Interface:**
```bash
python calendar/scripts/list_events.py --account ctiis --date tomorrow
python calendar/scripts/list_events.py --account ctiis --date 2026-03-03 --calendar "Мои события"
```

---

### 2. Schedule a Meeting

**User Request Examples:**
- "Schedule a 1-hour meeting with Ivan tomorrow at 3pm"
- "Book a team sync for next Monday 10am"
- "Create recurring standup every day at 9am"

**Requirements:**
- Create VEVENT with proper UID generation
- Support single and recurring events
- Required fields:
  - Summary (title)
  - Start datetime
  - End datetime or duration
  - Calendar selection (default: "Мои события")
- Optional fields:
  - Description
  - Location (physical or URL)
  - Attendees (email list with RSVP status)
  - Recurrence rule (RRULE)
  - Reminders (VALARM)

**Attendee Handling:**
- Add attendees as ATTENDEE properties
- Set PARTSTAT (NEEDS-ACTION for new invites)
- Send calendar invites via Yandex (if API supports)

**CLI Interface:**
```bash
python calendar/scripts/create_event.py \
  --account ctiis \
  --summary "Team Sync" \
  --start "2026-03-03T15:00:00" \
  --duration 60 \
  --calendar "Мои события" \
  --attendees "user@yandex.ru,colleague@yandex.ru" \
  --description "Weekly team synchronization"
```

Bind an existing Telemost conference instead of creating a new one:

```bash
python calendar/scripts/create_event.py \
  --account ctiis \
  --summary "Team Sync" \
  --start "2026-03-12T10:00:00" \
  --duration 60 \
  --telemost-conference-id 1234567890
```

---

### 3. Reschedule a Meeting

**User Request Examples:**
- "Move my 3pm meeting to 4pm"
- "Reschedule Сбер ЦФА to next week"
- "Change the team sync to 30 minutes earlier"

**Requirements:**
- Search by event title (fuzzy matching) or partial datetime
- Handle ambiguous matches (list candidates when multiple found)
- Update options:
  - New start/end time
  - New duration
  - New date (keep time)
  - New location
- Preserve:
  - Original attendees (re-send invites if time changes)
  - Description and other metadata
  - Recurrence pattern (optionally update series or single instance)

**Conflict Detection:**
- Check for overlapping events at new time
- Warn user about conflicts
- Option to proceed anyway

**CLI Interface:**
```bash
python calendar/scripts/reschedule.py \
  --account ctiis \
  --search "Сбер ЦФА" \
  --date "2026-03-03" \
  --new-start "2026-03-03T16:00:00"

python calendar/scripts/reschedule.py \
  --account ctiis \
  --event-uid "uuid-here" \
  --postpone 30  # minutes
```

---

### 4. Cancel a Meeting

**User Request Examples:**
- "Cancel my 3pm meeting"
- "Delete the team sync"
- "Remove all recurring standups"

**Requirements:**
- Search by title or datetime
- Cancel options:
  - Single instance (for recurring events)
  - Entire series
- Send cancellation notices to attendees
- Move to cancelled/removed state in CalDAV

**Safety:**
- Confirmation prompt for multi-attendee events
- Require --force flag for non-interactive deletion

**CLI Interface:**
```bash
python calendar/scripts/cancel.py \
  --account ctiis \
  --search "Team Sync" \
  --date "2026-03-03"

python calendar/scripts/cancel.py \
  --account ctiis \
  --event-uid "uuid-here" \
  --cancel-series
```

---

### 5. Find Available Slots for Multiple People

**User Request Examples:**
- "Find 2 hours for three of us towards the weekend"
- "When are Boris, Ivan, and Maria all free on Thursday?"
- "Suggest meeting times for 1 hour next week with these attendees"

**Requirements:**
- Accept multiple account identifiers (from agent config mailboxes)
- Query across multiple calendars per person
- Constraints:
  - Duration (required)
  - Date range (required, e.g., "towards the weekend")
  - Time window (optional, e.g., "business hours 9-18")
  - Preferred days (optional, e.g., "prefer Tuesday/Thursday")
- Return sorted options:
  - Primary: slots where all attendees are free
  - Secondary: slots with minimal conflicts

**Algorithm:**
1. Fetch all events for all attendees in date range
2. Build free/busy matrix with 15-minute granularity
3. Find continuous blocks matching duration
4. Score and rank by:
   - Number of conflicts (0 = best)
   - Proximity to preferred days
   - Time of day preferences

**Output Format:**
```json
{
  "query": {
    "duration_minutes": 120,
    "attendees": ["bdi", "ctiis", "colleague@yandex.ru"],
    "date_range": {"start": "2026-03-03", "end": "2026-03-07"},
    "time_window": {"start": "09:00", "end": "18:00"}
  },
  "slots": [
    {
      "start": "2026-03-04T10:00:00+03:00",
      "end": "2026-03-04T12:00:00+03:00",
      "all_free": true,
      "attendee_status": {
        "bdi": "free",
        "ctiis": "free",
        "colleague@yandex.ru": "free"
      }
    },
    {
      "start": "2026-03-05T14:00:00+03:00",
      "end": "2026-03-05T16:00:00+03:00",
      "all_free": true,
      "attendee_status": { ... }
    }
  ],
  "alternative_slots": [...]
}
```

**CLI Interface:**
```bash
python calendar/scripts/find_slots.py \
  --duration 120 \
  --attendees "bdi,ctiis,colleague@yandex.ru" \
  --from "tomorrow" \
  --to "friday" \
  --time-window "9:00-18:00"

python calendar/scripts/find_slots.py \
  --duration 60 \
  --attendees "bdi,ctiis" \
  --next-available
```

---

### 6. Add or Modify Telemost Meetings (Integration Point)

**Status**: Implemented via `telemost/` skill

**Requirements:**
- This skill provides calendar manipulation primitives
- Telemost skill calls calendar skill to:
  - Create calendar event when meeting is scheduled
  - Update event when Telemost details change
  - Add the real Telemost `join_url` to event location/description
  - Cancel event when Telemost meeting is deleted
- Existing Telemost conference binding is supported via `--telemost-conference-id`
- `--telemost-conference-id` is mutually exclusive with:
  - `--telemost-access-level`
  - `--telemost-waiting-room`
  - `--telemost-cohosts`

**Integration Contract:**
```python
# calendar/skill_api.py exposes:
def create_event_with_telemost(
    account: str,
    summary: str,
    start: datetime,
    duration_minutes: int,
    telemost_link: str,
    attendees: List[str]
) -> Event:
    """Create event with Telemost link in location field."""
    
def update_telemost_link(
    account: str,
    event_uid: str,
    telemost_link: str
) -> Event:
    """Update existing event with new/updated Telemost link."""
```

**Data Contract:**
- Telemost link stored in `LOCATION`
- Event description may include Telemost dial-in info
- `calendar/scripts/create_event.py` now creates the Telemost conference first, then writes the returned `join_url` into the event
- if `--telemost-conference-id` is provided, the script fetches the existing conference and writes that conference's `join_url` into the event instead of creating a new conference

---

## Technical Design

### Directory Structure
```
calendar/
├── calendar.md              # This file
├── scripts/
│   ├── list_events.py
│   ├── create_event.py
│   ├── reschedule.py
│   ├── cancel.py
│   └── find_slots.py
├── lib/
│   ├── __init__.py
│   ├── client.py            # CalDAV client wrapper
│   ├── events.py            # Event CRUD operations
│   ├── availability.py      # Free/busy logic
│   └── parser.py            # Natural language date parsing
└── tests/
```

### Dependencies
```
caldav>=2.2.6
icalendar>=7.0.2
python-dateutil>=2.8.0
```

### Configuration Extension
Add shared defaults to root `config.json` and per-agent overrides to `yandex-data/config.agent.json`:
```json
{
  "calendar": {
    "default_calendar": "Мои события",
    "business_hours": {"start": "09:00", "end": "18:00"},
    "slot_granularity_minutes": 15
  }
}
```

### State Files
```
{data_dir}/
├── auth/{account}.token     # Existing OAuth tokens
└── calendar/
    └── freebusy_cache.json  # Optional: cache for availability queries
```

---

## Error Handling

### Common Error Cases
1. **Token expired** → Prompt for re-auth via `mail/scripts/oauth_setup.py`
2. **Calendar not found** → List available calendars
3. **Event not found** → Suggest similar titles, show events for that date
4. **Conflict detected** → Show conflicting events, ask for confirmation
5. **Attendee calendar unavailable** → Mark as unknown in availability matrix

### Error Format
```json
{
  "error": "calendar_not_found",
  "message": "Calendar 'Work' not found",
  "available_calendars": ["Мои события", "Не забыть"]
}
```

---

## Security Considerations

1. **Token storage**: Reuse existing `{data_dir}/auth/{account}.token` pattern
2. **No token logging**: Never log OAuth tokens
3. **Calendar permissions**: Respect Yandex ACLs (read-only vs read-write)
4. **Attendee privacy**: Don't expose other users' full event details in availability queries

---

## Future Enhancements

1. **Webhooks**: Subscribe to calendar changes (if Yandex supports)
2. **Timezone handling**: Better support for cross-timezone scheduling
3. **Busy-only queries**: Use freebusy endpoint if available (more efficient)
4. **Color coding**: Support calendar colors in output
5. **Categories/Tags**: Support iCalendar CATEGORIES for filtering
6. **ICS export**: Generate .ics files for external sharing

---

## References

- CalDAV RFC: https://datatracker.ietf.org/doc/html/rfc4791
- iCalendar RFC: https://datatracker.ietf.org/doc/html/rfc5545
- Yandex OAuth: https://yandex.ru/dev/id/doc/dg/oauth/reference/concepts.html
- CalDAV Python library: https://github.com/python-caldav/caldav
