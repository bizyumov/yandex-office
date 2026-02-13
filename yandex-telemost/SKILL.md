---
name: yandex-telemost
description: >
  Process Yandex Telemost meeting data from two email types: "Конспект встречи"
  (transcript with YandexGPT summary) and "Запись встречи" (video/audio links).
  Merges both by meeting UID, transforms transcripts with UTC diarization, and
  outputs structured meeting documents. Use when processing Telemost meetings
  or when new files appear in the incoming directory.
license: MIT
metadata:
  author: bizyumov
  version: "1.0"
---

# Yandex Telemost

Process Telemost meeting transcripts and recordings into structured documents.

## Quick Start

```bash
# Process all unprocessed meetings from incoming/
python scripts/process_meeting.py --incoming data/incoming --output documents/meetings

# Without archiving (keep originals)
python scripts/process_meeting.py --incoming data/incoming --no-archive
```

## How It Works

### Two Email Types from Telemost

| Type | Subject | Arrives | Contains |
|------|---------|---------|----------|
| Конспект | `Конспект встречи от DD.MM.YYYY` | ~30 min | Transcript `.txt` + YandexGPT summary |
| Запись | `Запись встречи «Title» от DD.MM.YYYY` | ~hours | Video/audio `yadi.sk` links |

Both contain `https://telemost.yandex.ru/j/{MEETING_UID}` — used as merge key.

### Processing Pipeline

1. **Scan** `incoming/` for dirs with `meta.json`
2. **Group** by `meeting_uid` from metadata
3. **Merge** data from "Конспект" + "Запись" emails
4. **Transform** transcript: MSK timestamps → UTC diarization
5. **Output** to `documents/meetings/{MEETING_UID}/`
6. **Archive** processed dirs (configurable)

### Output Structure

```
documents/meetings/{MEETING_UID}/
    transcript.txt        # Transformed transcript (UTC diarization)
    summary.txt           # YandexGPT auto-summary
    meeting.meta.json     # Merged metadata
    recording/            # Downloaded by yandex-disk (optional)
        video.mp4
        audio.mp3
```

### Partial Meetings

A meeting may have only "Конспект" (no recording) or only "Запись" (no transcript).
The processor outputs what's available and marks `"partial": true` in metadata.
On next run, if the missing email has arrived, it merges and updates the output.

### Manual Drops

Files placed manually in `incoming/` (without going through yandex-mail) are also
processed. The dir doesn't need a UID — any dir with a `.txt` file is treated as work.

## Transcript Transformation

- Parses `DD.MM.YYYY с HH:MM (MSK)` → reference UTC
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

- `scripts/process_meeting.py` — Main orchestrator (scan, group, merge, output)
- `scripts/process_transcript.py` — Transcript transformation logic
- `references/telemost-format.md` — Email types and transcript format docs
