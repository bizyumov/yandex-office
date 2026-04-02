---
name: yandex
description: Shared Yandex skill pack for Mail, Disk, Telemost, Calendar, Contacts, Directory, Cloud, Forms, and Tracker on this OpenClaw host. Yandex Search now lives in a separate standalone skill repo.
homepage: https://github.com/bizyumov/yandex-skills
license: MIT
compatibility: Python 3.10+, per-skill dependencies, network access for Yandex APIs
metadata:
  author: bizyumov
  version: "1.1"
  openclaw:
    emoji: "🟡"
    requires:
      bins:
        - python3
---

# yandex

A collection of [agentskills.io](https://agentskills.io/specification)-compliant skills for working with Yandex platform services.

## Structure

This is a meta-skill containing multiple Yandex service integrations:

```text
yandex/
├── SKILL.md                  (this file: root index)
├── config.json               (shared defaults)
├── config.agent.example.json (workspace override example)
├── mail/
│   └── mail.md
├── calendar/
│   └── calendar.md
├── contacts/
│   └── contacts.md
├── directory/
│   └── directory.md
├── disk/
│   └── disk.md
├── telemost/
│   └── telemost.md
├── cloud/
│   └── cloud.md
└── forms/
    └── forms.md
```

## Where To Read Each Skill

- Mail: `mail/mail.md`
- Calendar: `calendar/calendar.md`
- Contacts: `contacts/contacts.md`
- Directory: `directory/directory.md`
- Disk: `disk/disk.md`
- Telemost: `telemost/telemost.md`
- Cloud: `cloud/cloud.md`
- Forms: `forms/forms.md`
- Tracker: `tracker/tracker.md`

## Skills

| Skill | Description |
|-------|-------------|
| [mail](mail/) | Mail / Почта: generic email fetcher via IMAP XOAUTH2 — saves emails to incoming/ |
| [calendar](calendar/) | Calendar / Календарь: CalDAV integration for Yandex Calendar — list/create/update events, find slots, Telemost binding |
| [contacts](contacts/) | Contacts / Контакты: CardDAV integration for Yandex Contacts — fuzzy lookup, create/update contacts |
| [directory](directory/) | Directory / Директория: Yandex 360 Directory API — users, departments, groups, and org-aware identity data |
| [telemost](telemost/) | Telemost / Телемост: process Telemost emails, manage real conferences, and admin Telemost org defaults |
| [disk](disk/) | Disk / Диск: download files from Yandex Disk, upload files to Disk, and manage public or organization-only share links (Telemost links may require OAuth) |
| [cloud](cloud/) | Cloud / Облако: deploy serverless functions to Yandex Cloud |
| [forms](forms/) | Forms / Формы: export form responses from Yandex Forms — download results as XLSX or JSON |
| [tracker](tracker/) | Tracker / Трекер: manage tasks in Yandex Tracker — create, search, update issues, manage Agile boards |

## Migration Note

Yandex Search moved to the standalone `yandex-search-skill` repository:

- https://github.com/bizyumov/yandex-search-skill

Use that skill when you need Yandex Cloud Search API v2. This `yandex` meta-skill no longer includes search instructions.

## Shared Configuration

All Yandex sub-skills use the same two-level config:

- root `config.json` for shared defaults
- `{cwd}/yandex-data/config.agent.json` for agent-specific overrides

Root `config.json`:

```json
{
  "data_dir": "yandex-data",
  "urls": {
    "oauth": "https://oauth.yandex.ru/authorize",
    "disk_api": "https://cloud-api.yandex.net",
    "telemost_api": "https://cloud-api.yandex.net/v1/telemost-api",
    "search_api": "https://searchapi.api.cloud.yandex.net",
    "operations_api": "https://operation.api.cloud.yandex.net"
  },
  "imap": { "server": "imap.yandex.com", "port": 993 },
  "mail": {
    "since": "off",
    "filters": { "sender": "keeper@telemost.yandex.ru" },
    "fetch": { "sleep_seconds": 0.5 },
    "state_file": "state.json"
  }
}
```

## Regression Tests

Run the checked-in regression suite from the repo root:

```bash
./scripts/test_regression.sh
```

Agent override example:

```json
{
  "mailboxes": [{ "name": "primary", "email": "user@example.com" }]
}
```

`data_dir` is resolved from the actual process CWD, so the canonical runtime path is `{cwd}/yandex-data/`.

## Data Directory

Runtime data lives **outside** the repo at `{data_dir}/`:

```text
{data_dir}/
├── auth/bdi.token      # OAuth tokens (per-account)
├── incoming/           # mail writes here
├── state.json          # UID tracking
├── meetings/           # telemost output (bucketed by month)
│   └── 2026-02/
│       └── 2026-02-24_18-19_bdi_1000349120/
│           ├── transcript.txt
│           ├── summary.txt
│           └── meeting.meta.json
├── archive/            # Processed email dirs
└── forms/              # forms export output
    └── {form_id}/
        ├── responses_2026-03-03_080512.xlsx
        └── meta.json
```

## Typical Workflow

```text
[Mail] -> incoming/ -> [Telemost] -> meetings/
                           |
                           +-> [Disk] (optional recording downloads)
```

1. `mail` fetches emails on a cron schedule, saves to `{data_dir}/incoming/`
2. `telemost` enriches Telemost emails, groups by meeting UID, merges + transforms
3. `disk` (optional) downloads recording links

Disk note:

- organization-only sharing is live-verified for the documented `public_settings.accesses[].macros` payload
- `available_until` behaves as an absolute Unix timestamp; omitting it means infinite sharing
- resource metadata does not reliably echo ACLs back, so link behavior must be verified through the public-resource endpoints

Telemost calendar note:

- `calendar/scripts/create_event.py` can create a new Telemost conference or bind an existing one with `--telemost-conference-id`
- existing-conference binding is strict and cannot be combined with new-conference flags

Important: for "what is new", always run `mail/scripts/fetch_emails.py` first. Do not treat `archive/` or `meetings/` as source-of-truth for new messages.

## Telemost Meeting Directory Contract

`telemost` stores each meeting under:

`{data_dir}/meetings/{YYYY-MM}/{YYYY-MM-DD_HH-MM}_{mailbox}_{MEETING_UID}/`

Where:

1. `YYYY-MM` is derived from first-seen meeting timestamp.
2. Meeting folder starts with local date/time prefix `YYYY-MM-DD_HH-MM`.
3. Date/time prefix is immediately followed by mailbox tag (`bdi`, `work`, etc.).
4. Folder always ends with meeting UID (`_{MEETING_UID}` or `_unknown`).
5. Folder routing is constrained by same-day wildcard candidate matching.

Processing semantics:

1. Emails inside each `meeting_uid` are processed in natural `imap_uid` order.
2. For each email event, resolver scans `YYYY-MM/YYYY-MM-DD_*-*_{mailbox}_{meeting_uid}`.
3. If exactly one candidate exists, transcript/summary/metadata are appended there.
4. If no candidate exists, a new `YYYY-MM/YYYY-MM-DD_HH-MM_{mailbox}_{meeting_uid}` directory is created.
5. If multiple same-day candidates exist, event processing fails fast (integrity error, no heuristic pick).
6. `meeting.meta.json.media_links` is append-unique (deduplicated, order preserved).
7. `meeting.meta.json` stores recording links only in `media_links` (no `video_url`/`audio_url` fields).

Migration for existing folders:

```bash
python3 telemost/scripts/migrate_meeting_dirs.py --dry-run
python3 telemost/scripts/migrate_meeting_dirs.py
```

## Telemost Recording OAuth Caveat

Yandex Disk links that look public (for example `yadi.sk/d/...`) may still require OAuth for Telemost recordings.

- With token: API may return downloadable link.
- Without token: API may return `404` for existing Telemost resources.
- `HEAD` requests are not a reliable probe for availability.

Use token-based auth when handling Telemost media links.

## Installation

### Full clone

```bash
git clone https://github.com/bizyumov/yandex-skills.git
```

### Single skill (sparse checkout)

```bash
git clone --filter=blob:none --sparse https://github.com/bizyumov/yandex-skills.git
cd yandex
git sparse-checkout set mail

# Add more skills later
git sparse-checkout add telemost disk
```

## OAuth Setup

### Token Format

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

Canonical convention is `token.<service>`. Each service stores and resolves its own token directly.

### Generate a Token

```bash
# Recommended: default preconfigured app from config.json, ready approval link
python3 scripts/oauth_setup.py --email user@yandex.ru --account bdi --service mail

# Recommended: choose a non-default preconfigured app variant
python3 scripts/oauth_setup.py --email user@yandex.ru --account bdi --service disk --app disk-full

# Advanced: explicit client ID and explicit scope override
python3 scripts/oauth_setup.py --client-id DISK_CLIENT_ID --scope cloud_api:disk.write --scope cloud_api:disk.app_folder --email user@yandex.ru --account bdi --service disk
```

Recommended flow:

- keep the app catalog in root `config.json` under `oauth_apps.catalog`
- keep default app bindings in root `config.json` under `oauth_apps.service_defaults`
- use `--app <app_id>` only when selecting a non-default variant
- run `python3 scripts/oauth_setup.py --service <name> ...`
- the generated URL omits `scope=` by default and uses the app's baked-in permissions
- new token files are created automatically on first save

Advanced flow:

- pass `--client-id` explicitly
- add `--scope` values when you need a one-off override or debugging path

Important:

- Mail and Disk can use different OAuth apps and therefore different Client IDs.
- If an OAuth app's permission set changes later, tokens must be reissued.
- For mail fetching, prefer read-only scope (`mail:imap_ro`).

## OAuth App Registration

| Step | URL |
|------|-----|
| Register API app | https://yandex.ru/dev/id/doc/ru/register-api |
| Create new API key | https://oauth.yandex.ru/client/new/api |
| View existing tokens | https://oauth.yandex.ru/ |

## Service-Specific Documentation

| Service | Documentation |
|---------|---------------|
| Yandex Disk API | https://yandex.ru/dev/disk-api/doc/ru/concepts/quickstart |
| Yandex Mail IMAP | https://yandex.ru/support/mail/mail-clients/others.html |
| Yandex Cloud CLI | https://cloud.yandex.com/docs/cli/quickstart |

## Migration Note

This repository now uses `yandex/` with `mail/`, `disk/`, `telemost/`, and `cloud/` plus the other non-search service folders.
Old `yandex-*` paths are removed as part of hard cutover.

## License

MIT
