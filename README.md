# yandex-office

A collection of [agentskills.io](https://agentskills.io/specification)-compliant skills for working with Yandex platform services.

## Skills

| Skill | Description |
|-------|-------------|
| [mail](mail/) | Mail / Почта: generic email fetcher via IMAP XOAUTH2 — saves emails to incoming/ |
| [calendar](calendar/) | Calendar / Календарь: CalDAV integration for Yandex Calendar — list/create/update events, find slots, Telemost binding |
| [contacts](contacts/) | Contacts / Контакты: CardDAV integration for Yandex Contacts — fuzzy lookup, create/update contacts |
| [directory](directory/) | Directory / Директория: Yandex 360 Directory API — users, departments, groups, and org-aware identity data |
| [telemost](telemost/) | Telemost / Телемост: process Telemost emails, manage real conferences, and admin Telemost org defaults |
| [disk](disk/) | Disk / Диск: download files, upload files, and manage public or organization-only share links |
| [cloud](cloud/) | Cloud / Облако: deploy serverless functions to Yandex Cloud |

## Migration Note

Yandex Search has moved to the standalone `yandex-search-skill` repository:

- https://github.com/bizyumov/yandex-search-skill

This repository now covers the remaining shared Yandex service skills only.

## Shared Configuration

All Yandex sub-skills use the same two-level config:

- skill defaults in root `config.json`
- agent overrides in `{data_dir}/config.agent.json`
- default runtime location is `./yandex-data` from the agent workspace CWD
- scripts that expose `--data-dir` can override that path explicitly

Root `config.json`:

```json
{
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

Workspace `{data_dir}/config.agent.json`:

```json
{
  "accounts": [{ "name": "alex", "email": "user@example.com" }]
}
```

During first onboarding, OpenClaw must invoke the full path to `scripts/oauth_setup.py` with no account arguments while the current process CWD is still the agent workspace. Bootstrap resolves `data_dir` as `./yandex-data` from that workspace CWD, creates `{data_dir}/config.agent.json` and runtime directories there, and normal runtime then requires that initialized data dir. If you run a script manually from the shared skill root, pass `--data-dir`.

### Data Directory

Runtime data lives **outside** the repo at `{data_dir}/`:

```
{data_dir}/
├── auth/alex.token      # OAuth tokens (per-account)
├── incoming/           # mail writes here
├── state.json          # UID/date tracking keyed by mailbox name
├── meetings/ # telemost output (bucketed by month)
│   └── 2026-02/
│       └── 2026-02-24_18-19_alex_1000349120/
│           ├── transcript.txt
│           ├── summary.txt
│           └── meeting.meta.json
└── archive/            # Processed email dirs
```

## Installation

### Full clone

```bash
git clone https://github.com/bizyumov/yandex-office.git
```

### Single skill (sparse checkout)

```bash
git clone --filter=blob:none --sparse https://github.com/bizyumov/yandex-office.git
cd yandex-office
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
3. Date/time prefix is immediately followed by mailbox tag (`alex`, `work`, etc.).
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

## OAuth Setup

### Mental Model

```text
OpenClaw workspace cwd
  -> bootstrap resolves absolute data_dir from $PWD/yandex-data
  -> {data_dir}/config.agent.json
     -> accounts + service-specific overrides

Skill config.json
  -> oauth_apps.service_defaults.<service> selects the default app_id
  -> oauth_apps.catalog.<app_id> stores app name, client_id, service, and baked-in scopes

python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --service <service> [--app <app_id>] --account <account> --email <email>
  -> resolves app_id from oauth_apps.service_defaults unless --app is passed
  -> reads oauth_apps.catalog.<app_id>
  -> generates approval URL
  -> creates auth/{account}.token on first save if needed
  -> stores token under auth/{account}.token as token.<service>
  -> stores app_id/client_id/scopes under token_meta.token.<service>

runtime clients
  -> resolve token.<service>
  -> verify scopes from token_meta.token.<service>.scopes
```

### Default Service Scopes

| Service | Default scopes | Typical use |
|---------|----------------|-------------|
| `mail` | `mail:imap_ro` | Read-only IMAP fetch |
| `disk` | `cloud_api:disk.read` | Download/read-only links |
| `telemost` | `telemost-api:conferences.create`, `telemost-api:conferences.delete`, `telemost-api:conferences.read`, `telemost-api:conferences.update` | Conference lifecycle |
| `tracker` | `tracker:read` | Read/search issues |
| `forms` | `forms:read` | Export/discover forms |
| `directory` | `directory:read_users`, `directory:read_departments`, `directory:read_groups`, `directory:read_domains`, `directory:read_external_contacts`, `directory:read_organization` | Org graph reads |
| `calendar` | `calendar:all` | User calendar access |
| `contacts` | `addressbook:all` | Contacts read/write |

### Recommended Preconfigured App Set

Use one preconfigured app per capability family instead of one universal app:

| App scenario | Service key | Recommended scopes | Why |
|-------------|-------------|--------------------|-----|
| Mail read-only | `mail` | `mail:imap_ro` | Safest default for fetchers |
| Disk read-only | `disk` | `cloud_api:disk.read` | Covers downloads and Telemost media reads |
| Telemost conference admin | `telemost` | `telemost-api:conferences.create`, `telemost-api:conferences.delete`, `telemost-api:conferences.read`, `telemost-api:conferences.update` | Full meeting lifecycle |
| Tracker read-only | `tracker` | `tracker:read` | Search and inspect issues |
| Forms export | `forms` | `forms:read` | Form discovery and export |
| Directory read-only | `directory` | `directory:read_users`, `directory:read_departments`, `directory:read_groups`, `directory:read_domains`, `directory:read_external_contacts`, `directory:read_organization` | Org lookups without broader admin write access |
| Calendar user access | `calendar` | `calendar:all` | Current user calendar operations |

If you want write-capable variants later, keep them as separate app scenarios instead of broadening the default read-only app.

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
`token_meta` is optional but recommended: clients use it to validate granted scopes and generate a corrected approval URL when a token is under-scoped.

### Add an Account

```bash
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email user@yandex.ru --account alex
```

This updates `{data_dir}/config.agent.json` and does not prompt for a token.

### Generate a Token

```bash
# Recommended: default preconfigured app from config.json, ready approval link
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email user@yandex.ru --account alex --service mail

# Recommended: choose a non-default preconfigured app variant
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email user@yandex.ru --account alex --service disk --app disk-full

# Advanced: explicit client ID and explicit scope override
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --client-id DISK_CLIENT_ID --scope cloud_api:disk.write --scope cloud_api:disk.app_folder --email user@yandex.ru --account alex --service disk
```

Recommended flow:

- keep the checked-in app catalog in `config.json` under `oauth_apps.catalog`
- keep service defaults in `config.json` under `oauth_apps.service_defaults`
- when `--service` is used, `oauth_setup.py` prints the default profile and any other configured profiles for that service
- use `--app <app_id>` only when you need a non-default variant such as `disk-full`, `forms-full`, `tracker-full`, or `directory-full`
- add the account first with `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email <email> --account <name>` when needed
- then run `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email <email> --account <name> --service <name>`
- the generated URL omits `scope=` by default and relies on the OAuth app's baked-in permissions

Advanced flow:

- pass `--client-id` explicitly
- optionally add `--scope` overrides for debugging or one-off operator flows

Important:

- Mail and Disk can use different OAuth apps and therefore different Client IDs.
- If an OAuth app's permissions change later, previously issued tokens must be reissued.
- For mail fetching, prefer read-only scope (`mail:imap_ro`).

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
| Yandex Cloud CLI | https://cloud.yandex.com/docs/cli/quickstart |

## License

MIT
