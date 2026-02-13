---
name: yandex-mail
description: >
  Fetch emails and attachments from Yandex Mail via IMAP with OAuth2
  authentication. Downloads new messages into a structured incoming directory
  for downstream processing. Classifies Telemost emails by type (transcript
  vs recording), extracts meeting UIDs, and enriches metadata. Use when
  checking for new emails, downloading attachments, or setting up automated
  email polling from Yandex mailboxes.
license: MIT
compatibility: Requires Python 3.10+, network access to imap.yandex.ru
metadata:
  author: bizyumov
  version: "1.0"
---

# Yandex Mail

Automated email fetcher for Yandex Mail via IMAP XOAUTH2.

## Quick Start

```bash
# One-time: set up OAuth token
python scripts/oauth_setup.py --client-id YOUR_ID --email user@yandex.ru --service mail

# Fetch new emails
python scripts/fetch_emails.py --config /path/to/config.json

# Or via cron-safe wrapper
scripts/fetch.sh
```

## What It Does

1. Connects to Yandex Mail via IMAP XOAUTH2
2. Searches for new emails from configured sender (e.g. `keeper@telemost.yandex.ru`)
3. Classifies each email: "Конспект встречи" (transcript) or "Запись встречи" (recording)
4. Extracts meeting UID from `https://telemost.yandex.ru/j/{UID}` in body
5. Downloads attachments (preserving original filenames)
6. Extracts email body (HTML→text)
7. Writes structured directory to `incoming/` with enriched `meta.json`
8. Persists UID state after each email (crash-safe)

## Output Structure

```
incoming/{YYYY-MM-DD}_{mailbox}_uid{N}/
    {original_filename}.txt    # Telemost transcript (if "Конспект")
    email_body.txt             # Email body converted to text
    meta.json                  # Enriched metadata
```

### meta.json Fields

```json
{
  "imap_uid": 2550,
  "mailbox": "mailbox1",
  "subject": "Конспект встречи от 08.02.2026",
  "email_type": "konspekt",
  "meeting_uid": "3500330089",
  "meeting_title": null,
  "media_links": [],
  "attachments": ["2026-02-08 19:07 (MSK) 5981404294.txt"],
  "date": "2026-02-08"
}
```

## Cron Setup

```bash
# Every 15 minutes
*/15 * * * * /path/to/yandex-mail/scripts/fetch.sh

# PID file prevents concurrent runs automatically
```

## Configuration

See `config.example.json`. Set `YANDEX_MAIL_DATA` env var to override data directory.

## Files

- `scripts/fetch_emails.py` — Main fetcher (CLI + Python API)
- `scripts/oauth_setup.py` — Interactive OAuth token wizard (mail + disk)
- `scripts/fetch.sh` — Cron-safe shell wrapper with PID lock
- `references/imap-xoauth2.md` — XOAUTH2 protocol notes
