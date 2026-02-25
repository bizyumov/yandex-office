---
name: yandex-telemost
description: 'Process Yandex Telemost meeting data: enrich incoming emails with meeting metadata, merge "summary" (transcript) and "recording" (video/audio) emails by meeting UID, transform transcripts with UTC diarization. Use when processing Telemost meetings or when new emails arrive in the incoming directory.'
license: MIT
metadata:
  author: bizyumov
  version: "2.2"
---

# Yandex Telemost

Process Telemost meeting transcripts and recordings into structured documents.

## Quick Start

```bash
# Process all unprocessed meetings (auto-discovers config.json)
python scripts/process_meeting.py

# Cron-safe wrapper (PID lock, forwards CLI args)
./scripts/process.sh

# Or specify paths explicitly
python scripts/process_meeting.py --incoming /path/to/incoming --output /path/to/output

# Without archiving (keep originals in incoming/)
python scripts/process_meeting.py --no-archive

# Wrapper with forwarded args
./scripts/process.sh --no-archive --download-recordings
```

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
7. **Append outputs** into single meeting files in one stable directory per `meeting_uid`
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

HTML is not used by `yandex-telemost` processing.

### Output Structure

```
{data_dir}/meetings/{YYYY-MM}/{YYYY-MM-DD_HH-MM}_{mailbox}_{MEETING_UID}/
    transcript.txt        # Single append-only transcript with per-email separators
    summary.txt           # Single append-only summary with per-email separators
    meeting.meta.json     # Non-destructive merged metadata
    recordings/           # Downloaded by yandex-disk (optional)
        video.mp4
        audio.mp3
```

Directory naming:

- Month bucket folder: `YYYY-MM` (derived from first-seen meeting timestamp)
- Meeting folder prefix: `YYYY-MM-DD_HH-MM`
- Prefix must be followed by mailbox tag (e.g. `bdi`, `ctiis`)
- Final segment is meeting UID: `_{MEETING_UID}` (or `_unknown`)
- Example: `2026-02/2026-02-24_18-19_bdi_1000349120`

Directory stability rule:

- The first processed email for a given `meeting_uid` creates the meeting directory.
- All subsequent emails for the same `meeting_uid` are resolved into that same directory (located by UID).

### Migrating Existing Meeting Folders

Run once to normalize previously generated folders:

```bash
# Preview changes
python scripts/migrate_meeting_dirs.py --dry-run

# Apply changes
python scripts/migrate_meeting_dirs.py
```

The migration script scans `{data_dir}/meetings/**/meeting.meta.json`,
computes the canonical v2 path, and renames each directory in-place.

## Cron Wrapper (`process.sh`)

Use `scripts/process.sh` for scheduled runs to avoid overlapping executions:

- Uses PID lock file: `/tmp/yandex-telemost-process.pid`
- Skips run if previous process is still active
- Passes all CLI args through to `process_meeting.py`
- Uses `YANDEX_TELEMOST_CONFIG` env var to override config path

Example:

```bash
*/30 * * * * /path/to/yandex-telemost/scripts/process.sh --download-recordings
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
- `scripts/process.sh` — Cron-safe wrapper with PID lock (passes args through)
- `scripts/process_transcript.py` — Transcript transformation logic
- `scripts/migrate_meeting_dirs.py` — Rename existing meeting dirs to v2 layout
- `scripts/test_telemost.py` — Unit and integration tests
- `references/telemost-format.md` — Email types and transcript format docs
