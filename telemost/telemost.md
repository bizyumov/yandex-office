---
name: telemost
description: 'Telemost / Телемост — process Yandex Telemost meeting data and manage real Telemost conferences. Use when processing Telemost meeting emails or when creating/updating conferences for calendar scheduling.'
license: MIT
metadata:
  author: bizyumov
  version: "2026.04.10"
---

# Yandex Telemost / Телемост

Process Telemost meeting transcripts and recordings into structured documents, and create or update real Telemost conferences via the Telemost API.

## Quick Start

```bash
# Create a real conference (defaults: PUBLIC access, PUBLIC waiting room, no cohosts)
python3 scripts/conference.py create --account mary

# Read conference info
python3 scripts/conference.py get --account mary --id <conference_id>

# Update conference settings
python3 scripts/conference.py update --account mary --id <conference_id> --waiting-room ADMINS

# From the agent workspace CWD: reuse an existing conference when creating a calendar event
python3 calendar/scripts/create_event.py \
  --account mary \
  --summary "Проектный созвон" \
  --start "2026-03-12T10:00:00" \
  --duration 45 \
  --telemost-conference-id <conference_id>

# Read organization defaults applied to new conferences
python3 scripts/settings.py get --account mary

# Update organization defaults
python3 scripts/settings.py update --account mary --waiting-room-calendar ORGANIZATION

# Process all unprocessed meetings (uses shared config discovery from the workspace)
python3 scripts/process_meeting.py

# Cron-safe wrapper (PID lock, forwards CLI args)
./scripts/process.sh

# Or specify paths explicitly
python3 scripts/process_meeting.py --incoming ./incoming --output ./meetings

# Without archiving (keep originals in incoming/)
python3 scripts/process_meeting.py --no-archive

# Wrapper with forwarded args
./scripts/process.sh --no-archive --download-recordings
```

## Conference Management

The Telemost API client uses `https://cloud-api.yandex.net/v1/telemost-api` and `token.telemost`.

Default conference settings:

- `access_level=PUBLIC`
- `waiting_room_level=PUBLIC`
- `cohosts=[]`

Supported operations:

- create conference
- get conference info
- update conference settings
- get organization settings
- update organization settings
- bind an existing conference to a new calendar event through `calendar/scripts/create_event.py --telemost-conference-id ...`

Optional create/update fields:

- `access_level`: `PUBLIC` or `ORGANIZATION`
- `waiting_room_level`: `PUBLIC`, `ORGANIZATION`, or `ADMINS`
- `cohosts`: comma-separated email list
- `live_stream`: access level, title, and description

Required OAuth scopes:

- `telemost-api:conferences.create`
- `telemost-api:conferences.read`
- `telemost-api:conferences.update`

Live stream creation may require a paid Yandex 360 tariff. The Telemost API is available only for Yandex 360 organization accounts.

## Organization Settings

Telemost exposes organization-level defaults for newly created conferences through:

- `GET /organizations/{org_id}/settings`
- `PUT /organizations/{org_id}/settings`

Supported settings fields:

- `waiting_room_level_adhoc`
- `waiting_room_level_calendar`
- `cloud_recording_email_receivers`
- `cloud_recording_allowed_roles`
- `summarization_email_receivers`
- `summarization_allowed_roles`

Waiting-room values:

- `PUBLIC`
- `ORGANIZATION`
- `ADMINS`

Role-list values:

- `OWNER`
- `INTERNAL_COHOST`
- `INTERNAL_MEMBER`

`settings.py update` sends the full organization-settings payload expected by the API. You can provide it either:

- from a JSON file with `--settings-file`
- or by composing the supported fields from CLI flags

When Yandex returns additional settings fields beyond the documented core set, the client preserves them if you round-trip the full JSON payload from `settings.py get` back into `settings.py update --settings-file ...`.

`org_id` resolution order:

1. `--org-id`
2. `org_id` stored in the account token file

If neither is available, the command fails and you must supply `--org-id` or persist `org_id` into the token file. Reliable API discovery of `org_id` requires an admin token with `directory:read_organization`.

## How It Works

### Two Email Types from Telemost

| Type | Subject | Arrives | Contains |
|------|---------|---------|----------|
| Summary | `Конспект встречи от DD.MM.YYYY` | ~30 min | Transcript `.txt` + YandexGPT summary |
| Recording | `Запись встречи «Title» от DD.MM.YYYY` | ~hours | Video/audio `yadi.sk` links |

Both contain `https://telemost.yandex.ru/j/{MEETING_UID}` — used as merge key.

### Processing Pipeline

1. **Enrich** incoming emails: classify type, extract meeting_uid/title/links/start_local
2. **Scan** enriched emails from `{data_dir}/incoming/`
3. **Group** by `meeting_uid`
4. **Sort events** inside each meeting by `imap_uid` (natural integer order)
5. **Process each email event one-by-one** (no destructive overwrite)
6. **Transform** transcript: local start + `[HH:MM:SS]` offsets → absolute UTC diarization
7. **Route output directory by same-day wildcard invariant**
8. **Archive** processed dirs (configurable)

### Enrichment Phase

Before processing, `enrich_incoming()` scans the incoming directory and for each email from `keeper@telemost.yandex.ru`:

- Classifies subject → `"summary"` or `"recording"`
- Extracts meeting UID from plain-text `email_body.txt`
- Extracts meeting title from subject (for recording emails)
- Extracts yadi.sk media links from plain-text `email_body.txt`
- Extracts meeting local start from body text (`dd.mm.yyyy в hh:mm`)
- Saves YandexGPT summary text (for summary emails)
- Updates meta.json with enriched fields

HTML is not used by `telemost` processing.

### Output Structure

```
{data_dir}/meetings/{YYYY-MM}/{YYYY-MM-DD_HH-MM}_{mailbox}_{MEETING_UID}/
    transcript.txt        # Single append-only transcript with per-email separators
    summary.txt           # Single append-only summary with per-email separators
    meeting.meta.json     # Non-destructive merged metadata
    recordings/           # Downloaded by disk (optional)
        video.mp4
        audio.mp3
```

Directory naming:

- Month bucket folder: `YYYY-MM` (derived from first-seen meeting timestamp)
- Meeting folder prefix: `YYYY-MM-DD_HH-MM`
- Prefix must be followed by mailbox tag (e.g. `alex`, `mary`)
- Final segment is meeting UID: `_{MEETING_UID}` (or `_unknown`)
- Example: `2026-02/2026-02-24_18-19_alex_1000349120`

Directory routing rule (same-day wildcard, single-candidate invariant):

- For each incoming email event, resolver scans month bucket with:
  `YYYY-MM/YYYY-MM-DD_*-*_{mailbox}_{meeting_uid}`.
- If exactly one candidate directory exists, data is appended there.
- If no candidate exists, a new directory is created from:
  `YYYY-MM/YYYY-MM-DD_HH-MM_{mailbox}_{meeting_uid}`.
- If more than one candidate exists, processing fails fast for that event (explicit integrity error, no heuristic pick).

### Migrating Existing Meeting Folders

Run once to normalize previously generated folders:

```bash
# Preview changes
python3 scripts/migrate_meeting_dirs.py --dry-run

# Apply changes
python3 scripts/migrate_meeting_dirs.py
```

The migration script scans `{data_dir}/meetings/**/meeting.meta.json`,
computes the canonical v2 path, and renames each directory in-place.

## Cron Wrapper (`process.sh`)

Use `scripts/process.sh` for scheduled runs to avoid overlapping executions:

- Uses a PID lock file named `telemost-process.pid` in the system temp directory
- Skips run if previous process is still active
- Passes all CLI args through to `process_meeting.py`
- Uses `YANDEX_TELEMOST_CONFIG` env var to override config path

Example:

```bash
*/30 * * * * cd telemost && ./scripts/process.sh --download-recordings
```

### Event Processing and Partial Meetings

A meeting may have only "summary" (no recording) or only "recording" (no transcript).
The processor appends whatever is available and marks `"partial": true` until both transcript and recording links are present.
On later runs, newly arrived emails for the same `meeting_uid` are appended (not overwritten).

Append semantics:

- `transcript.txt` contains one section per processed summary email.
- `summary.txt` contains one section per processed summary email.
- Each section starts with a separator containing at least `imap_uid` and email type.
- `meeting.meta.json.media_links` is append-unique (deduplicated, first-seen order preserved).
- `meeting.meta.json.source_emails` accumulates all processed source emails for the meeting.
- `meeting.meta.json` does not use `video_url` or `audio_url`; use `media_links` only.

### Console Output Policy

- Default mode prints one compact line per processed meeting.
- Detailed report (summary preview, links, speaker list) is shown only with `--verbose`.
- Summary preview strips the default Telemost frontmatter line (`Встреча проходила ...`).

## Transcript Transformation

- Parses local meeting start (`dd.mm.yyyy в hh:mm`) as reference
- Converts `[HH:MM:SS]` offsets → absolute UTC timestamps on speaker lines
- Removes all `[HH:MM:SS]` markers from body

**Before:**
```
Борис Изюмов:
[00:00:10] Привет, начинаем.
```

**After:**
```
2026-02-08T16:07:10Z Борис Изюмов:
Привет, начинаем.
```

## Files

- `scripts/process_meeting.py` — Main orchestrator (enrich, scan, group, merge, output)
- `scripts/conference.py` — Create, read, and update real Telemost conferences
- `scripts/settings.py` — Read and update Telemost organization settings
- `lib/client.py` — Telemost API client
- `scripts/process.sh` — Cron-safe wrapper with PID lock (passes args through)
- `scripts/process_transcript.py` — Transcript transformation logic
- `scripts/migrate_meeting_dirs.py` — Rename existing meeting dirs to v2 layout
- `scripts/test_telemost.py` — Unit and integration tests
- `references/telemost-format.md` — Email types and transcript format docs
