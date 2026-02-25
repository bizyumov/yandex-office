# yandex-skills

A collection of [agentskills.io](https://agentskills.io/specification)-compliant skills for working with Yandex platform services.

## Skills

| Skill | Description |
|-------|-------------|
| [yandex-mail](yandex-mail/) | Generic email fetcher via IMAP XOAUTH2 — saves emails to incoming/ |
| [yandex-telemost](yandex-telemost/) | Enrich and process Telemost meetings — merge summary + recording, UTC diarization |
| [yandex-disk](yandex-disk/) | Download public files from Yandex Disk (yadi.sk links) |
| [yandex-search](yandex-search/) | Web search via Yandex Cloud Search API v2 |
| [yandex-cloud](yandex-cloud/) | Deploy serverless functions to Yandex Cloud |

## Shared Configuration

All skills use a shared `config.json` at the repository root:

```json
{
  "data_dir": "../../data/yandex",
  "urls": {
    "oauth": "https://oauth.yandex.ru/authorize",
    "disk_api": "https://cloud-api.yandex.net",
    "search_api": "https://searchapi.api.cloud.yandex.net",
    "operations_api": "https://operation.api.cloud.yandex.net"
  },
  "imap": { "server": "imap.yandex.com", "port": 993 },
  "mailboxes": [{ "name": "bdi", "email": "bdi@boevayaslava.ru" }],
  "mail": {
    "filters": { "sender": "keeper@telemost.yandex.ru" },
    "state_file": "state.json"
  }
}
```

`data_dir` is relative to the config file. Scripts auto-discover config by walking up directories.

### Data Directory

Runtime data lives **outside** the repo at `{data_dir}/`:

```
{data_dir}/
├── auth/bdi.token      # OAuth tokens (per-account)
├── incoming/           # yandex-mail writes here
├── state.json          # UID tracking
├── meetings/ # yandex-telemost output (bucketed by month)
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
cd yandex-skills
git sparse-checkout set yandex-mail

# Add more skills later
git sparse-checkout add yandex-telemost yandex-disk
```

## Typical Workflow

```
[Yandex Mail] → incoming/ → [Yandex Telemost] → meetings/
                                    ↓
                             [Yandex Disk] (download recordings)
```

1. **yandex-mail** fetches emails on a cron schedule, saves to `{data_dir}/incoming/`
2. **yandex-telemost** enriches Telemost emails, groups by meeting UID, merges + transforms
3. **yandex-disk** (optional) downloads video/audio from yadi.sk links

Each skill is self-contained and can be used independently.

## Telemost Meeting Directory Contract

`yandex-telemost` stores each meeting under:

`{data_dir}/meetings/{YYYY-MM}/{YYYY-MM-DD_HH-MM}_{mailbox}_{MEETING_UID}/`

Where:

1. `YYYY-MM` is derived from first-seen meeting timestamp.
2. Meeting folder starts with local date/time prefix `YYYY-MM-DD_HH-MM`.
3. Date/time prefix is immediately followed by mailbox tag (`bdi`, `ctiis`, etc.).
4. Folder always ends with meeting UID (`_{MEETING_UID}` or `_unknown`).
5. Folder is created on first email for that `meeting_uid` and reused for all later emails with the same UID.

Processing semantics:

1. Emails inside each `meeting_uid` are processed in natural `imap_uid` order.
2. `transcript.txt` is a single append-only file with per-email separators.
3. `summary.txt` is a single append-only file with per-email separators.
4. `meeting.meta.json.media_links` is append-unique (deduplicated, order preserved).

Migration for existing folders:

```bash
python yandex-telemost/scripts/migrate_meeting_dirs.py --dry-run
python yandex-telemost/scripts/migrate_meeting_dirs.py
```

## OAuth Setup

### Token Format

```json
{
  "email": "user@yandex.ru",
  "token.mail": "y0_...",
  "token.disk": "y0_..."
}
```

Flat keys (`token.mail`, `token.disk`), one file per account at `{data_dir}/auth/{account}.token`.

### Generate a Token

```bash
# Mail token (use Client ID from an OAuth app that has mail/IMAP scope)
python yandex-mail/scripts/oauth_setup.py --client-id MAIL_CLIENT_ID --email user@yandex.ru --account bdi --service mail

# Disk token (you MAY use a different Client ID from an app that has Disk scope)
python yandex-mail/scripts/oauth_setup.py --client-id DISK_CLIENT_ID --email user@yandex.ru --account bdi --service disk
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
