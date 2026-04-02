---
name: mail
description: Mail / Почта — fetch emails and attachments from Yandex Mail via IMAP with OAuth2 authentication. Downloads new messages into a structured incoming directory for downstream processing by specialized skills. Generic fetcher with no business logic — just saves emails matching configured filters.
license: MIT
compatibility: Requires Python 3.10+, network access to imap.yandex.ru
metadata:
  author: bizyumov
  version: "2.4"
---

# Yandex Mail / Почта

Generic email fetcher for Yandex Mail via IMAP XOAUTH2. Saves incoming emails matching configured filters into a structured directory for downstream processing by other skills.

## Quick Start

```bash
# From the Yandex skill root: set up OAuth token for mail (read-only IMAP scope)
python scripts/oauth_setup.py --email user@yandex.ru --account bdi --service mail

# Fetch new emails from the agent workspace
python scripts/fetch_emails.py

# Fetch at most N new messages in this run (global cap)
python scripts/fetch_emails.py --num 20
```

> Recommended: use the default Mail app from root `config.json` (`oauth_apps.service_defaults.mail`) so the approval URL can use the app's baked-in scopes without passing `--client-id` each time. If you also need Disk access, run `python scripts/oauth_setup.py --service disk ...` from the Yandex skill root.

## What It Does

1. Loads shared root `config.json`
2. Loads `{cwd}/yandex-data/config.agent.json`
3. Connects to Yandex Mail via IMAP XOAUTH2
4. Searches for new emails from configured sender filter
5. Downloads attachments (preserving original filenames)
6. Saves email body (text + HTML)
7. Writes structured directory to `{data_dir}/incoming/` with generic `meta.json`
8. Persists UID state after each email (crash-safe, atomic writes)
9. Optionally limits intake with `--num` to avoid flood on newly added mailboxes
10. Optionally narrows IMAP search with global `SINCE` mode for large mailboxes
11. Applies configurable sleep between message-processing iterations (global)

## Flood Control (`--num`)

Use `--num` to cap the total number of newly fetched messages per run:

```bash
python scripts/fetch_emails.py --num 25
```

Behavior:

- Cap is global across all configured mailboxes.
- Messages are fetched in ascending UID order (oldest unseen first).
- Once the cap is reached, remaining mailboxes are skipped for that run.
- UID state is persisted after each successfully processed message.
- `--num` must be a positive integer.

## Optional `SINCE` Mode

For large mailboxes, you can globally limit IMAP search to messages sent since a date.

Root config (`config.json`):

```json
{
  "mail": {
    "since": "on",
    "filters": {
      "sender": "keeper@telemost.yandex.ru"
    }
  }
}
```

Behavior:

- When `mail.since` is `"on"`, fetcher reads per-mailbox `last_received_date` from `state.json` and applies IMAP `SINCE <date>`.
- Search criteria is an intersection (AND): `SINCE` + sender criteria.
- Sender criteria remains based on configured full address and is queried as `FROM "<left-of-@>" AND FROM "<right-of-@>"`.
- State now persists both:
  - `last_uid`
  - `last_received_date` (UTC date extracted from fetched email timestamp)

Reference:

- RFC 3501 `SEARCH` keys and AND intersection semantics: https://www.ietf.org/rfc/rfc3501.html

## Global Fetch Throttle

You can configure a global pause between `_process_email` iterations:

```json
{
  "mail": {
    "fetch": {
      "sleep_seconds": 0.5
    }
  }
}
```

Behavior:

- Applies between processed messages within a mailbox loop.
- Unit: seconds.
- Default: `0.5`.
- `0` disables the delay.
- Negative/invalid values fall back to default or clamp to `0`.

## CLI Output

Default stdout is intentionally brief JSON:

```json
{
  "fetched_total": 12,
  "mailboxes": {
    "bdi": 4,
    "ctiis": 8
  }
}
```

Verbose mode (`-v`) keeps detailed logs in stderr/logger output.

## Output Structure

```
{data_dir}/incoming/{YYYY-MM-DD}_{mailbox}_uid{N}/
    {original_filename}.txt    # Attachments (preserved names)
    email_body.txt             # Email body (text)
    email_body.html            # Email body (raw HTML, for downstream parsing)
    meta.json                  # Generic metadata
```

### meta.json Fields

```json
{
  "imap_uid": 2550,
  "mailbox": "bdi",
  "subject": "Конспект встречи от 08.02.2026",
  "sender": "Хранитель встреч Телемоста <keeper@telemost.yandex.ru>",
  "timestamp": "2026-02-08T09:27:00Z",
  "attachments": ["2026-02-08 19:07 (MSK) 5981404294.txt"],
  "dir_name": "2026-02-08_bdi_uid2550"
}
```

No business logic fields — downstream skills (telemost, etc.) enrich meta.json as needed.

## Configuration

Uses shared root `config.json` plus agent-local `yandex-data/config.agent.json`. Key fields:

- `data_dir` — Base directory for data (auth, incoming, state)
- `imap.server` / `imap.port` — IMAP connection settings
- `mailboxes` — Agent-local mailbox list in `config.agent.json`
- `mail.filters.sender` — FROM address filter
- `mail.since` — `"on"`/`"off"` toggle for state-driven IMAP `SINCE` filtering
- `mail.fetch.sleep_seconds` — Global sleep between `_process_email` iterations (seconds, default `0.5`)
- `mail.state_file` — UID tracking file

## Token Format

```json
{
  "email": "user@yandex.ru",
  "token.mail": "y0_...",
  "token.disk": "y0_..."
}
```

Stored at `{data_dir}/auth/{account}.token` with 600 permissions.

## Files

- `scripts/fetch_emails.py` — Main fetcher (CLI + Python API)
- `scripts/oauth_setup.py` — Shared interactive OAuth token wizard for all Yandex sub-skills (run from the Yandex skill root)
- `scripts/fetch.sh` — Cron-safe shell wrapper with PID lock (passes `--num` and other args through)
