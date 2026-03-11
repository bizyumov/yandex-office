# yandex

A collection of [agentskills.io](https://agentskills.io/specification)-compliant skills for working with Yandex platform services.

## Skills

| Skill | Description |
|-------|-------------|
| [mail](mail/) | Generic email fetcher via IMAP XOAUTH2 — saves emails to incoming/ |
| [telemost](telemost/) | Enrich/process Telemost emails, manage real Telemost conferences, and admin Telemost org defaults |
| [disk](disk/) | Download public files from Yandex Disk, upload files to Disk, and manage public or organization-only share links |
| [search](search/) | Web search via Yandex Cloud Search API v2 |
| [cloud](cloud/) | Deploy serverless functions to Yandex Cloud |

## Shared Configuration

All Yandex sub-skills use the same two-level config:

- skill defaults in root `config.json`
- agent overrides in `{cwd}/yandex-data/config.agent.json`

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

Workspace `yandex-data/config.agent.json`:

```json
{
  "mailboxes": [{ "name": "primary", "email": "user@example.com" }]
}
```

`data_dir` is resolved from the actual process CWD. Run scripts from the agent workspace, not from the repo root.

### Data Directory

Runtime data lives **outside** the repo at `{data_dir}/`:

```
{data_dir}/
├── auth/bdi.token      # OAuth tokens (per-account)
├── incoming/           # mail writes here
├── state.json          # UID tracking
├── meetings/ # telemost output (bucketed by month)
│   └── 2026-02/
│       └── 2026-02-24_18-19_bdi_1000349120/
│           ├── transcript.txt
│           ├── summary.txt
│           └── meeting.meta.json
└── archive/            # Processed email dirs
```

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

## Typical Workflow

```
[Yandex Mail] → incoming/ → [Yandex Telemost] → meetings/
                                    ↓
                             [Yandex Disk] (download recordings)
```

1. **mail** fetches emails on a cron schedule, saves to `{data_dir}/incoming/`
2. **telemost** enriches Telemost emails, groups by meeting UID, merges + transforms
3. **disk** (optional) downloads video/audio from yadi.sk links

Disk note:

- organization-only sharing is live-verified for the documented `public_settings.accesses[].macros` payload
- `available_until` behaves as an absolute Unix timestamp; omitting it means infinite sharing
- metadata does not reliably echo ACLs back, so share verification depends on public-resource endpoint behavior

Telemost calendar note:

- `calendar/scripts/create_event.py` can create a new Telemost conference or bind an existing one with `--telemost-conference-id`
- existing-conference binding is strict and cannot be combined with new-conference flags

Each skill is self-contained and can be used independently.

## Telemost Meeting Directory Contract

`telemost` stores each meeting under:

`{data_dir}/meetings/{YYYY-MM}/{YYYY-MM-DD_HH-MM}_{mailbox}_{MEETING_UID}/`

Where:

1. `YYYY-MM` is derived from first-seen meeting timestamp.
2. Meeting folder starts with local date/time prefix `YYYY-MM-DD_HH-MM`.
3. Date/time prefix is immediately followed by mailbox tag (`bdi`, `ctiis`, etc.).
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
python telemost/scripts/migrate_meeting_dirs.py --dry-run
python telemost/scripts/migrate_meeting_dirs.py
```

## OAuth Setup

### Token Format

```json
{
  "email": "user@yandex.ru",
  "token.auth": "y0_...",
  "token.mail": "y0_...",
  "token.disk": "y0_..."
}
```

Canonical convention is `token.<skill>` for every sub-skill. Legacy aliases are migrated in place where needed (`token.org` -> `token.directory`, contacts currently duplicates calendar auth into `token.contacts`).

### Generate a Token

```bash
# Mail token (use Client ID from an OAuth app that has mail/IMAP scope)
python mail/scripts/oauth_setup.py --client-id MAIL_CLIENT_ID --email user@yandex.ru --account bdi --service mail

# Disk token (you MAY use a different Client ID from an app that has Disk scope)
python mail/scripts/oauth_setup.py --client-id DISK_CLIENT_ID --email user@yandex.ru --account bdi --service disk
```

> Important: Mail and Disk can use different OAuth apps and therefore different Client IDs.
> Use a Client ID that is configured for the requested service scope.
> For mail fetching, prefer read-only scope (`mail:imap_ro`).

### OAuth App Registration

| Step | URL |
|------|-----|
| Register API app | https://yandex.ru/dev/id/doc/ru/register-api |
| Create new API key | https://oauth.yandex.ru/client/new/api |
| View existing tokens | https://oauth.yandex.ru/ |

### Service-Specific Documentation

| Service | Documentation |
|---------|---------------|
| Yandex Disk API | https://yandex.ru/dev/disk-api/doc/ru/concepts/quickstart |
| Yandex Mail IMAP | https://yandex.ru/support/mail/mail-clients/others.html |
| Yandex Cloud Search API | https://yandex.cloud/ru/docs/search-api/ |
| Yandex Cloud CLI | https://cloud.yandex.com/docs/cli/quickstart |

## License

MIT
