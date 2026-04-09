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

Ask the user to verify that IMAP + OAuth is enabled for the target mailbox first:

- EN: Open Yandex Mail in a browser, go to Settings → Mail clients (direct URL: `https://mail.yandex.ru/#setup/client`), enable `From imap.yandex.ru server via IMAP` and `App passwords and OAuth tokens`, then save.
- RU: Откройте Яндекс Почту в браузере, перейдите в Настройки → Почтовые программы (прямая ссылка: `https://mail.yandex.ru/#setup/client`), включите `С сервера imap.yandex.ru по протоколу IMAP` и `Пароли приложений и OAuth-токены`, затем сохраните изменения.

```bash
# From the agent workspace CWD, using the full path to the shared Yandex skill:
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email user@yandex.ru --account alex --service mail

# Fetch new emails with the default filter profile
python3 scripts/fetch_emails.py

# Fetch at most N new messages in this run (global cap)
python3 scripts/fetch_emails.py --num 20

# Run a named filter profile
python3 scripts/fetch_emails.py --filter forms-debug

# Run an ad-hoc one-off search without touching persistent cursor state
python3 scripts/fetch_emails.py --sender "Мария" --subject "Fwd:" --mailbox alex --dry-run
```

> Recommended: use the default Mail app from root `config.json` (`oauth_apps.service_defaults.mail`) so the approval URL can use the app's baked-in scopes without passing `--client-id` each time. If you also need Disk access, run `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email <email> --account <name> --service disk` from the agent workspace CWD.

## What It Does

1. Loads shared root `config.json`
2. Loads `{data_dir}/config.agent.json` from the resolved runtime data dir
3. Connects to Yandex Mail via IMAP XOAUTH2
4. Resolves the active mail filter profile or ad-hoc CLI overrides
5. Searches for new emails using sender / subject / date criteria
6. Supports UTF-8 IMAP fallback for non-ASCII search values
7. Maintains per-filter cursor state in `state.json`
8. Supports one-off non-persistent searches for debugging / backfills
9. Downloads attachments (preserving original filenames)
10. Saves email body (text + HTML)
11. Writes structured directory to `{data_dir}/incoming/` with generic `meta.json`
12. Persists UID state after each email (crash-safe, atomic writes) only for persistent profile runs
13. Optionally limits intake with `--num` to avoid flood on newly added mailboxes
14. Optionally narrows IMAP search with global `SINCE` mode for large mailboxes
15. Applies configurable sleep between message-processing iterations (global)

## Flood Control (`--num`)

Use `--num` to cap the total number of newly fetched messages per run:

```bash
python3 scripts/fetch_emails.py --num 25
```

Behavior:

- Cap is global across all configured mailboxes.
- Messages are fetched in ascending UID order (oldest unseen first).
- Once the cap is reached, remaining mailboxes are skipped for that run.
- UID state is persisted after each successfully processed message.
- `--num` must be a positive integer.

## Named Filters And Ad-Hoc Overrides

`mail.filters` now supports named profiles:

```json
{
  "mail": {
    "filters": {
      "default": "telemost",
      "profiles": {
        "telemost": {
          "sender": "keeper@telemost.yandex.ru"
        },
        "forms-debug": {
          "sender": "forms@yandex.ru",
          "subject": "New response"
        }
      }
    }
  }
}
```

CLI options:

- `--filter NAME` selects a named profile and keeps persistent state isolated to that profile.
- `--sender`, `--subject`, `--since-date`, `--before-date` override the active profile for the current run only.
- `--mailbox NAME` restricts the run to one configured mailbox.
- `--from-uid UID` starts from a specific UID floor for a one-off backfill.
- `--no-persist` disables state writes for the run.

Persistence rules:

- `--dry-run` never writes state.
- `--from-uid` is always treated as non-persistent.
- Raw CLI filter overrides are treated as ad-hoc runs and do not advance persistent cursors.
- Selecting a named profile with `--filter` and no ad-hoc overrides keeps normal persistent behavior.

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

- When `mail.since` is `"on"`, fetcher reads per-mailbox `last_received_date` from the active filter state in `state.json` and applies IMAP `SINCE <date>`.
- Search criteria is an intersection (AND): `SINCE` + sender criteria.
- Sender criteria remains based on configured full address and is queried as `FROM "<left-of-@>" AND FROM "<right-of-@>"`.
- State now persists both:
  - `last_uid`
  - `last_received_date` (UTC date extracted from fetched email timestamp)
- Named profiles keep separate state buckets so their cursors do not interfere with each other.

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
  "filter": "telemost",
  "persist_state": true,
  "fetched_total": 12,
  "mailboxes": {
    "alex": 4,
    "mary": 8
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
  "mailbox": "alex",
  "subject": "Конспект встречи от 08.02.2026",
  "sender": "Хранитель встреч Телемоста <keeper@telemost.yandex.ru>",
  "timestamp": "2026-02-08T09:27:00Z",
  "attachments": ["2026-02-08 19:07 (MSK) 5981404294.txt"],
  "dir_name": "2026-02-08_alex_uid2550"
}
```

No business logic fields — downstream skills (telemost, etc.) enrich meta.json as needed.

## Configuration

Uses shared root `config.json` plus agent-local `yandex-data/config.agent.json`. Key fields:

- `imap.server` / `imap.port` — IMAP connection settings
- `accounts` — Agent-local account list in `config.agent.json`
- `mail.filters.default` — default named mail filter profile
- `mail.filters.profiles.<name>.sender` — FROM filter criterion
- `mail.filters.profiles.<name>.subject` — SUBJECT filter criterion
- `mail.filters.profiles.<name>.since_date` / `before_date` — optional date bounds for that profile
- legacy `mail.filters.sender` — still supported as the implicit default profile
- `mail.since` — `"on"`/`"off"` toggle for state-driven IMAP `SINCE` filtering
- `mail.fetch.sleep_seconds` — Global sleep between `_process_email` iterations (seconds, default `0.5`)
- `mail.state_file` — shared state file with per-filter mailbox cursors
- runtime data dir defaults to `./yandex-data` from the agent workspace CWD, or `--data-dir` when explicitly passed

## Token Format

```json
{
  "email": "user@yandex.ru",
  "token.mail": "y0_...",
  "token.disk": "y0_...",
  "token_meta": {
    "token.mail": {
      "app_id": "mail-readonly",
      "client_id": "660686ff45f947f2ac6e3f6495a9ec74",
      "scopes": ["mail:imap_ro"]
    }
  }
}
```

Stored at `{data_dir}/auth/{account}.token` with 600 permissions. New token files are created automatically on first save.

## Files

- `scripts/fetch_emails.py` — Main fetcher (CLI + Python API)
- `scripts/oauth_setup.py` — Shared bootstrap/account/token setup tool for all Yandex sub-skills (invoke by full path from the agent workspace CWD)
- `scripts/fetch.sh` — Cron-safe shell wrapper with PID lock (passes `--num` and other args through)
