---
name: mail
description: Mail / Почта — fetch emails and attachments from Yandex Mail via IMAP with OAuth2 authentication. Downloads new messages into a structured incoming directory for downstream processing by specialized skills. Generic fetcher with no business logic — just saves emails matching configured filters.
license: MIT
compatibility: Requires Python 3.10+, network access to imap.yandex.ru
metadata:
  author: bizyumov
  version: "2026.04.10"
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

# Fetch new emails with all enabled configured filters
python3 scripts/fetch_emails.py

# Fetch at most N new messages in this run (global cap)
python3 scripts/fetch_emails.py --num 20

# Run one named filter only
python3 scripts/fetch_emails.py --filter forms

# Run an ad-hoc one-off search without touching persistent cursor state
python3 scripts/fetch_emails.py --sender "Мария" --subject "Fwd:" --mailbox alex --dry-run
```

> Recommended: use the default Mail app from root `config.json` (`oauth_apps.service_defaults.mail`) so the approval URL can use the app's baked-in scopes without passing `--client-id` each time. If you also need Disk access, run `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email <email> --account <name> --service disk` from the agent workspace CWD.

## What It Does

1. Loads shared root `config.json`
2. Loads `{data_dir}/config.agent.json` from the resolved runtime data dir
3. Connects to Yandex Mail via IMAP XOAUTH2
4. Resolves the configured filters for the run, or an ad-hoc CLI filter
5. Searches for new emails using sender / subject / date criteria
6. Supports UTF-8 IMAP fallback for non-ASCII search values
7. Maintains per-filter cursor state in `state.json`
8. Supports one-off non-persistent searches for debugging / backfills
9. Downloads attachments (preserving original filenames)
10. Saves email body (text + HTML)
11. Writes structured directory to `{data_dir}/incoming/<filter>/` with generic `meta.json`
12. Persists UID state after each email (crash-safe, atomic writes) only for persistent named-filter runs
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

## Filters And Ad-Hoc Overrides

`mail.filters` is a flat filter map:

```json
{
  "mail": {
    "filters": {
      "telemost": {
        "sender": "keeper@telemost.yandex.ru"
      },
      "forms": {
        "sender": "forms@yandex.ru",
        "subject": "New response",
        "enabled": false
      }
    }
  }
}
```

Filter key rules:

- filter keys are schema keys, not user-facing labels
- use lowercase English keys only: letters, digits, underscores
- keys must start with a letter
- keys are used for persistent state and incoming subdirectory names
- `default` is reserved for ad-hoc one-off runs and must not be used as a configured filter key

Run model:

- bare run with no filter CLI arguments executes all enabled configured filters across all selected mailboxes
- configured entries under `mail.filters` are peer filters such as `telemost` or `forms`
- the legacy top-level keys (`mail.filters.sender`, etc.) are still upgraded in-memory into `mail.filters.telemost`
- `enabled: false` excludes that named filter from bare runs
- `--filter NAME` runs exactly that named filter, even if `enabled: false`

CLI options:

- `--filter NAME` selects one named filter and keeps persistent state isolated to that filter.
- `--sender`, `--subject`, `--since-date`, `--before-date` run as one raw ad-hoc filter when used without `--filter`.
- raw ad-hoc criteria without `--filter` search mailbox history by default instead of inheriting a stored filter cursor.
- when `--filter NAME` is present, those same flags override that named filter for the current run only.
- use `--filter NAME` whenever you need one specific configured filter only; bare run means “all enabled filters”, not “one selected filter”
- `--mailbox NAME` restricts the run to one configured mailbox.
- `--from-uid UID` starts from a specific UID floor for a one-off backfill.
- `--no-persist` disables state writes for the run.

Persistence rules:

- `--dry-run` never writes state.
- `--from-uid` is always treated as non-persistent.
- Raw CLI filter overrides used without `--filter` are treated as ad-hoc runs and do not advance persistent cursors.
- Raw CLI filter overrides used without `--filter` also ignore stored filter cursors by default, so one-off lookups do not need `--from-uid 1` just to search mailbox history.
- Selecting a named filter with `--filter` and no ad-hoc overrides keeps normal persistent behavior.

## Heavy Output Handling

Broad mailbox lookups can return too much data for efficient inline assistant use. In dry-run mode:

- pending results stay inline only while the rendered payload is within the configured symbol threshold
- when the threshold is exceeded, the full result set is saved to `{data_dir}/latest-query/` instead
- stdout returns a compact summary plus `output_file`
- each spilled run clears the previous spill artifact from that directory
- if you want to keep a spilled file, copy it elsewhere before the next spilled run

Config:

```json
{
  "mail": {
    "output": {
      "max_inline_symbols": 2000,
      "spill_dir": "latest-query"
    }
  }
}
```

Notes:

- threshold is measured in symbols / characters, not bytes
- default `max_inline_symbols` is `2000`
- default `spill_dir` is `latest-query`

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
- Named filters keep separate state buckets so their cursors do not interfere with each other.

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

Large dry-run output example:

```json
{
  "dry_run": true,
  "filter": "telemost",
  "persist_state": false,
  "pending_total": 178,
  "pending": [],
  "mailboxes": {
    "work": 0
  },
  "output_file": "/path/to/yandex-data/latest-query/mail_dry_run_20260409T183247123456Z.json",
  "output_spilled": true,
  "inline_threshold_symbols": 2000,
  "output_notice": "Copy this file if you need to keep it. The next spilled run replaces the previous spill artifact."
}
```

Verbose mode (`-v`) keeps detailed logs in stderr/logger output.

## Output Structure

```
{data_dir}/incoming/{filter}/{YYYY-MM-DD}_{mailbox}_uid{N}/
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
  "filter": "telemost",
  "subject": "Конспект встречи от 08.02.2026",
  "sender": "Хранитель встреч Телемоста <keeper@telemost.yandex.ru>",
  "timestamp": "2026-02-08T09:27:00Z",
  "attachments": ["2026-02-08 19:07 (MSK) 5981404294.txt"],
  "dir_name": "2026-02-08_alex_uid2550",
  "dir_relpath": "telemost/2026-02-08_alex_uid2550"
}
```

No business logic fields — downstream skills (telemost, etc.) enrich meta.json as needed.

## Configuration

Uses shared root `config.json` plus agent-local `yandex-data/config.agent.json`. Key fields:

- `imap.server` / `imap.port` — IMAP connection settings
- `accounts` — Agent-local account list in `config.agent.json`
- `mail.filters.telemost` — configured Telemost filter definition
- `mail.filters.<name>.sender` — FROM filter criterion
- `mail.filters.<name>.subject` — SUBJECT filter criterion
- `mail.filters.<name>.since_date` / `before_date` — optional date bounds for that filter
- legacy `mail.filters.sender` — still supported and upgraded in-memory into `mail.filters.telemost.sender`
- `mail.since` — `"on"`/`"off"` toggle for state-driven IMAP `SINCE` filtering
- `mail.fetch.sleep_seconds` — Global sleep between `_process_email` iterations (seconds, default `0.5`)
- `mail.fetch.sleep_seconds` does not affect `--dry-run` search-only queries; it only throttles real `_process_email` iterations
- `mail.output.max_inline_symbols` — spill dry-run result sets to a file when inline output would exceed this symbol threshold (default `2000`)
- `mail.output.spill_dir` — relative output directory inside `{data_dir}` for spilled dry-run result files (default `latest-query`)
- sender and subject filters are literal IMAP substring matches; no additional query language is implemented
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
