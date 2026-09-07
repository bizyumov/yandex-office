---
name: telemost
description: 'Telemost / Телемост — process Yandex Telemost meeting data and manage real Telemost conferences. Use when processing Telemost meeting emails or when creating/updating conferences for calendar scheduling.'
license: MIT
metadata:
  author: bizyumov
  version: "2026.07.19"
---

# Yandex Telemost / Телемост

Process Telemost meeting transcripts and recordings into structured documents, and create or update real Telemost conferences via the Telemost API.

## Quick Start

### Process Telemost Transcripts

Fetch through the predefined Telemost mail filter first; then process the
received Telemost email directories.

```bash
python3 <full-path-to-yandex-office>/mail/scripts/fetch_emails.py \
  --filter telemost \
  --account <account> \
  --num <limit>
python3 <full-path-to-yandex-office>/telemost/scripts/process_meeting.py \
  --verbose
```

With recording downloads:

```bash
python3 <full-path-to-yandex-office>/telemost/scripts/process_meeting.py \
  --download-recordings \
  --verbose
```

```bash
# Create a real conference (defaults: PUBLIC access, PUBLIC waiting room, no cohosts)
python3 <full-path-to-yandex-office>/telemost/scripts/conference.py create --account mary

# Read conference info
python3 <full-path-to-yandex-office>/telemost/scripts/conference.py get --account mary --id <conference_id>

# Update conference settings
python3 <full-path-to-yandex-office>/telemost/scripts/conference.py update --account mary --id <conference_id> --waiting-room ADMINS

# Reuse an existing conference when creating a calendar event
python3 <full-path-to-yandex-office>/calendars/scripts/create_event.py \
  --account mary \
  --summary "Проектный созвон" \
  --start "2026-03-12T10:00:00" \
  --timezone Europe/Moscow \
  --duration 45 \
  --telemost-conference-id <conference_id>

# Read organization defaults applied to new conferences
python3 <full-path-to-yandex-office>/telemost/scripts/settings.py get --account mary

# Update organization defaults
python3 <full-path-to-yandex-office>/telemost/scripts/settings.py update --account mary --waiting-room-calendar ORGANIZATION

# Process all unprocessed meetings using CWD runtime discovery
python3 <full-path-to-yandex-office>/telemost/scripts/process_meeting.py

# Cron-safe wrapper (PID lock, forwards CLI args)
<full-path-to-yandex-office>/telemost/scripts/process.sh

# Or specify paths explicitly
python3 <full-path-to-yandex-office>/telemost/scripts/process_meeting.py --incoming ./incoming --output ./meetings

# Without archiving (keep originals in incoming/)
python3 <full-path-to-yandex-office>/telemost/scripts/process_meeting.py --no-archive

# Wrapper with forwarded args
<full-path-to-yandex-office>/telemost/scripts/process.sh --no-archive --download-recordings
```

## Conference Management

The Telemost API client uses `https://cloud-api.yandex.net/v1/telemost-api`.
Its low-level methods declare auth with `@yandex_api_method(...)`; runtime
selects eligible managed auth credentials by joining verified `client_id`
bindings to config-backed Telemost app scopes.

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
- bind an existing conference to a new calendar event through `python3 <full-path-to-yandex-office>/calendars/scripts/create_event.py --telemost-conference-id ...`

Conference create/update calls are write operations. They return the normalized
conference JSON available from the write response and request context; use
`get` when an explicit read/hydration step is needed.

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

`org_id` is supplied explicitly with `--org-id`. Auth is handled by the shared
decorator dispatcher.

## How It Works

### Two Email Types from Telemost

| Type | Subject | Arrives | Contains |
|------|---------|---------|----------|
| Summary | `Конспект встречи от DD.MM.YYYY` | ~30 min | Transcript `.txt` + YandexGPT summary |
| Recording | `Запись встречи «Title» от DD.MM.YYYY` | ~hours | Video/audio `yadi.sk` links |

Both contain `https://telemost.yandex.ru/j/{MEETING_UID}`. The unique meeting
occurrence key is `meeting_uid + start_utc`. IMAP UID is provenance only and
must not define meeting identity, fragment order, or output order.

All transcript fragments with the same `meeting_uid` and the same UTC calendar
day are written into one `transcript.txt`. Their order is ascending `start_utc`,
independent of email arrival order.

### Processing Pipeline

1. **Enrich** incoming emails: classify type, extract meeting_uid/title/links/start_local
2. **Scan** enriched emails from `{data_dir}/incoming/`
3. **Identify occurrence** by `meeting_uid + start_utc`
4. **Route fragments** with the same `meeting_uid` and UTC day into one file
5. **Upsert and rebuild** fragments in ascending `start_utc`; email arrival order is irrelevant
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

### Meeting Directory Contract

```
{data_dir}/meetings/{YYYY-MM}/{YYYY-MM-DD_HH-MM}_{account}_{MEETING_UID}/
    transcript.txt        # One deterministic transcript for same UID + UTC day
    summary.txt           # One deterministic summary for same UID + UTC day
    meeting.meta.json     # Non-destructive merged metadata
    recordings/           # Downloaded by disk (optional)
        video.mp4
        audio.mp3
```

Directory naming:

- Month bucket folder: `YYYY-MM` (derived from first-seen meeting timestamp)
- Meeting folder prefix: `YYYY-MM-DD_HH-MM`
- Prefix must be followed by account tag (e.g. `alex`, `mary`)
- Final segment is meeting UID: `_{MEETING_UID}` (or `_unknown`)
- Example: `2026-02/2026-02-24_18-19_alex_1000349120`

Directory routing rule (same-day wildcard, single-candidate invariant):

- Meeting identity is `meeting_uid + start_utc`; IMAP UID is provenance only.
- Fragments for the same `meeting_uid` and UTC day share one output directory.
- Final fragment order is ascending `start_utc`, regardless of arrival order.
- For each incoming email event, resolver scans month bucket with:
  `YYYY-MM/YYYY-MM-DD_*-*_{account}_{meeting_uid}`.
- If exactly one candidate directory exists, the fragment is upserted there.
- If no candidate exists, a new directory is created from:
  `YYYY-MM/YYYY-MM-DD_HH-MM_{account}_{meeting_uid}`.
- If more than one candidate exists, processing fails fast for that event (explicit integrity error, no heuristic pick).

### Migrating Existing Meeting Folders

Run once to normalize previously generated folders:

```bash
# Preview changes
python3 <full-path-to-yandex-office>/telemost/scripts/migrate_meeting_dirs.py --dry-run

# Apply changes
python3 <full-path-to-yandex-office>/telemost/scripts/migrate_meeting_dirs.py
```

The migration script scans `{data_dir}/meetings/**/meeting.meta.json`,
computes the canonical v2 path, and renames each directory in-place.

## Cron Wrapper (`process.sh`)

Use `<full-path-to-yandex-office>/telemost/scripts/process.sh` for scheduled runs to avoid overlapping executions:

- Uses a PID lock file named `telemost-process.pid` in the system temp directory
- Skips run if previous process is still active
- Passes all CLI args through to `process_meeting.py`
- Uses `YANDEX_TELEMOST_CONFIG` env var to override config path

Example:

```bash
*/30 * * * * <full-path-to-yandex-office>/telemost/scripts/process.sh --download-recordings
```

### Event Processing and Partial Meetings

A meeting may have only "summary" (no recording) or only "recording" (no transcript).
The processor upserts whatever is available and marks `"partial": true` until both transcript and recording links are present.
On later runs, fragments are merged by `meeting_uid + start_utc`, then the same-day file is rebuilt in ascending `start_utc`.

Deterministic merge semantics:

- `meeting_uid + start_utc` is the unique occurrence key.
- Reprocessing the same occurrence replaces the same logical fragment and does not append a duplicate.
- During rebuild, duplicate sections are removed, including legacy sections whose separators use the old `imap_uid` format.
- Legacy section identity is recovered from the directory meeting UID and the section transcript start UTC.
- If a legacy section key cannot be recovered, rebuild fails without overwriting the existing file.
- All fragments for the same `meeting_uid` and UTC day are rendered into one file.
- Email arrival order and IMAP UID do not affect the rendered order.
- A transcript separator contains `meeting_uid`, `start_utc`, and type; IMAP UID remains only in metadata provenance.
- `meeting.meta.json.media_links` is append-unique (deduplicated, first-seen order preserved).
- `meeting.meta.json.source_emails` accumulates all processed source emails for the meeting.
- `meeting.meta.json` does not use `video_url` or `audio_url`; use `media_links` only.

### Recording Link Auth

Yandex Disk links that look public, such as `yadi.sk/d/...`, may still require
OAuth for Telemost recordings.

- With managed auth for the selected account alias, the API may return a downloadable link.
- Without managed auth for that account, the API may return `404` for existing Telemost resources.
- `HEAD` requests are not a reliable availability probe.

Use `yandex-office` managed auth when handling Telemost media links. Recording
downloads use the source email account and the same runtime data directory used
by `process_meeting.py`.

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

- `telemost/scripts/process_meeting.py` — Main orchestrator (enrich, scan, group, merge, output)
- `telemost/scripts/conference.py` — Create, read, and update real Telemost conferences
- `telemost/scripts/settings.py` — Read and update Telemost organization settings
- `lib/client.py` — Telemost API client
- `telemost/scripts/process.sh` — Cron-safe wrapper with PID lock (passes args through)
- `telemost/scripts/process_transcript.py` — Transcript transformation logic
- `telemost/scripts/migrate_meeting_dirs.py` — Rename existing meeting dirs to v2 layout
- `telemost/scripts/test_telemost.py` — Unit and integration tests
- `references/telemost-format.md` — Email types and transcript format docs
