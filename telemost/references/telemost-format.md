# Telemost Email & Transcript Format

## Email Types

From `keeper@telemost.yandex.ru`, two email types arrive per meeting:

### "Конспект встречи" (Transcript)

- **Subject:** `Конспект встречи от DD.MM.YYYY`
- **Arrives:** Within ~30 minutes of meeting end
- **Body (HTML):** Contains YandexGPT auto-generated summary with topic headings
- **Attachment:** `.txt` file with raw transcript (diarized, timestamped)
- **Body contains:** `https://telemost.yandex.ru/j/{MEETING_UID}` link

### "Запись встречи" (Recording)

- **Subject:** `Запись встречи «{Title}» от DD.MM.YYYY`
  - Title is present only for calendar-created meetings
  - Meetings created ad-hoc have no `«title»` in subject
- **Arrives:** Within several hours of meeting end
- **Body (HTML):** Contains `yadi.sk` links to video and audio recordings
- **No attachment** (just links)
- **Body contains:** `https://telemost.yandex.ru/j/{MEETING_UID}` link

### Meeting UID

Both email types always contain a Telemost link with the meeting UID:
```
https://telemost.yandex.ru/j/3500330089
```

This UID is the **primary key** for merging data from both emails.
Extraction regex: `https://telemost\.yandex\.ru/j/(\d+)`

## Transcript File Format

### First Line (Header)

```
Встреча проходила DD.MM.YYYY с HH:MM (MSK). Длительность: X ч Y мин.
```

Example:
```
Встреча проходила 08.02.2026 с 19:07 (MSK). Длительность: 1 ч 23 мин.
```

### Diarization Lines

Speaker names appear on their own line, followed by their speech:

```
Борис Изюмов:
[00:00:10] Привет всем! Давайте начнём.
[00:00:15] Сегодня обсудим...

Анна Петрова:
[00:01:02] Да, я подготовила...
```

### Time Markers

- Format: `[HH:MM:SS]`
- Represent offset from meeting start
- May appear multiple times per speech block
- Should be converted to absolute UTC: `reference_timestamp + offset`

### Encoding

- File encoding: UTF-8
- Line endings: LF (Unix)

## Merging Logic

A single meeting may produce:
1. Only "Конспект" — process transcript, mark as partial
2. Only "Запись" — save recording links, mark as partial
3. Both — merge into complete meeting record

The processor groups incoming dirs by `meeting_uid` and merges all available data.

## Output Directory Contract (v2)

Processed meetings are stored as:

`{data_dir}/meetings/{YYYY-MM}/{YYYY-MM-DD_HH-MM}_{mailbox}_{MEETING_UID}/`

Rules:

- Parent folder is a month bucket (`YYYY-MM`).
- Meeting folder must start with local date/time prefix (`YYYY-MM-DD_HH-MM`).
- Date/time prefix must be followed by mailbox tag from source email metadata (`bdi`, `ctiis`, etc.).
- Suffix must include meeting UID (`_{MEETING_UID}`), or `_unknown` when UID is absent.

Example:

`meetings/2026-02/2026-02-24_18-19_bdi_1000349120/`
