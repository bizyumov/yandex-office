# yandex-office

A collection of [agentskills.io](https://agentskills.io/specification)-compliant skills for working with Yandex platform services.

Current release:

- version: `2026.05.04`
- version file: `VERSION`
- cumulative release notes: `CHANGELOG.md`

## Versioning

`yandex-office` uses dated skill versions in `YYYY.MM.DD` format.

- current released version lives in `VERSION`
- cumulative downloader-facing notes live in `CHANGELOG.md`
- release procedure lives in `RELEASING.md`

## Sub-Skills

| Skill | Description |
|-------|-------------|
| [mail](mail/) | Mail / Почта: generic email fetcher via IMAP XOAUTH2 — saves emails to incoming/ |
| [calendar](calendar/) | Calendar / Календарь: CalDAV integration for Yandex Calendar — list/create/update events, find slots, Telemost binding |
| [contacts](contacts/) | Contacts / Контакты: CardDAV integration for Yandex Contacts — fuzzy lookup, create/update contacts |
| [directory](directory/) | Directory / Директория: Yandex 360 Directory API — users, departments, groups, and org-aware identity data |
| [telemost](telemost/) | Telemost / Телемост: process Telemost emails, manage real conferences, and admin Telemost org defaults |
| [disk](disk/) | Disk / Диск: download files from Yandex Disk, upload files to Disk, and manage public or organization-only share links (Telemost links may require OAuth) |
| [forms](forms/) | Forms / Формы: export form responses from Yandex Forms — download results as XLSX or JSON |
| [tracker](tracker/) | Tracker / Трекер: manage tasks in Yandex Tracker — create, search, update issues, manage Agile boards |

## User Scenarios

This skill pack is designed to address the needs like:

- Receive recent yandex mail and process transcripts. Analyze today's morning daily transcript and submit tasks as github / gitlab issues
- Prepare action plan (or another doc) and put it on yandex disk, give me a public link
- Schedule a meeting in yandex calendar, invite Alex and Mary (get their emails from directory), attach a telemost link with public access
- ...and so on

If you want support for other scenarios, you are welcome to submit them under **Issues**.

## Migration Note

Yandex Search has moved to the standalone `yandex-search-skill` repository:

- https://github.com/bizyumov/yandex-search-skill

Yandex Cloud infrastructure guidance moved to the private standalone `yandex-cloud`
skill repository at `/opt/openclaw/shared/skills/yandex-cloud`.

This repository now covers the remaining shared Yandex 360 office service skills only.

## Shared Configuration

All Yandex sub-skills use the same two-level config:

- skill defaults in root `config.skill.json`
- agent overrides in `{data_dir}/config.agent.json`
- account aliases and OAuth state managed by setup/runtime auth
- default runtime location is `./yandex-data` from CWD
- scripts that expose `--data-dir` can override that path explicitly

Root `config.skill.json`:

```json
{
  "urls": {
    "oauth": "https://oauth.yandex.ru/authorize",
    "disk_api": "https://cloud-api.yandex.net",
    "telemost_api": "https://cloud-api.yandex.net/v1/telemost-api"
  },
  "imap": { "server": "imap.yandex.com", "port": 993 },
  "mail": {
    "since": "off",
    "filters": {
      "telemost": {
        "sender": "keeper@telemost.yandex.ru"
      }
    },
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
  "mail": {
    "filters": {
      "telemost": {
        "sender": "keeper@telemost.yandex.ru"
      },
      "forms": {
        "sender": "forms@yandex.ru",
        "subject": "New response"
      }
    }
  }
}
```

Mail filter notes:

- configured entries under `mail.filters` are peer filters such as `telemost` and `forms`
- legacy top-level keys like `mail.filters.sender` are still upgraded in-memory into `mail.filters.telemost`
- named filters support `enabled: false`; bare runs execute all enabled filters
- filter keys must be lowercase English schema keys because they are also used as incoming subdirectory names
- `default` is reserved for ad-hoc one-off runs and must not be used as a configured filter key
- `python3 mail/scripts/fetch_emails.py --filter <name>` runs exactly that named filter, even if it is disabled for bare runs
- raw CLI overrides such as `--sender` / `--subject` are treated as ad-hoc, do not advance persistent cursors, and search mailbox history by default when no `--filter` is selected
- sender and subject filters are literal IMAP substring matches; no extra query language is implemented
- large dry-run result sets spill into `{data_dir}/latest-query/`; the next spilled run replaces the previous artifact, so copy it elsewhere if you need to keep it

During first onboarding, OpenClaw must invoke the full path to `scripts/oauth_setup.py` with no account arguments while the current process CWD is unchanged. Bootstrap resolves `data_dir` as `./yandex-data` from that CWD, creates `{data_dir}/config.agent.json` and runtime directories there, and normal runtime then requires that initialized data dir. If you run a script manually from the shared skill root, pass `--data-dir`.

## Onboarding

### First run

1. Check `./yandex-data` in the current CWD.
2. If it does not exist, run `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py` from that CWD with no extra arguments.
3. Keep onboarding checks inside the current CWD.
4. Let `scripts/oauth_setup.py` create bootstrap files and directories.

### Adding Yandex accounts

Initialize the account alias with the provided email:

```bash
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email user@yandex.ru --account alex
```

Then issue or import an OAuth app token with the command below.

### Issuing OAuth App Tokens

```bash
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email user@yandex.ru --account alex --app mail-readonly
```

Behavior:

- complete OAuth in the browser, then paste the returned `access_token` into
  this exact hidden terminal input line:

```text
Paste the access_token here:
```

- `scripts/oauth_setup.py` verifies the pasted token and updates managed auth
- if the token value is already available and you need a non-interactive import,
  use this exact CLI:

```bash
IFS= read -rsp 'Paste access_token: ' YANDEX_ACCESS_TOKEN
printf '\n'
export YANDEX_ACCESS_TOKEN
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --from-env YANDEX_ACCESS_TOKEN
unset YANDEX_ACCESS_TOKEN
```

- Choose app IDs explicitly with `--app`; use the read/default app unless the
  user explicitly approves write-capable permissions.

### Data Directory

Runtime data lives **outside** the repo at `{data_dir}/`:

```
{data_dir}/
├── incoming/           # mail writes here
├── state.json          # UID/date tracking keyed by filter and mailbox
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

1. **mail** fetches emails on a cron schedule, saves to `{data_dir}/incoming/<filter>/`
2. **telemost** enriches Telemost emails, groups by meeting UID, merges + transforms
3. **disk** (optional) downloads video/audio from yadi.sk links

Important: for "what is new", always run `mail/scripts/fetch_emails.py` first. Do not treat `archive/` or `meetings/` as the source of truth for new messages.

Disk note:

- organization-only sharing is live-verified for the documented `public_settings.accesses[].macros` payload
- `available_until` behaves as an absolute Unix timestamp; omitting it means infinite sharing
- metadata does not reliably echo ACLs back, so share verification depends on public-resource endpoint behavior

Telemost recording OAuth caveat:

- links that look public (`yadi.sk/d/...`) may still require OAuth
- with token: API may return a downloadable link
- without token: API may return `404` for an existing Telemost resource
- `HEAD` requests are not a reliable availability probe

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
     -> agent-local app definitions + service-specific overrides

Skill config.skill.json
  -> oauth_apps.catalog marks the default app with `is_default: true`
  -> oauth_apps.catalog.<app_id> stores app name, client_id, and declared scopes

python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email <email> --account <account> --app mail-readonly
  -> reads oauth_apps.catalog.<app_id>
  -> generates approval URL
  -> verifies the pasted token to recover email + client_id
  -> creates or reuses the verified account alias
  -> updates managed auth storage
  -> adds an agent-local app definition only when the verified client_id is unknown

runtime clients
  -> call methods decorated with @yandex_api_method(...)
  -> join managed auth client_id bindings to config-backed app scopes
  -> choose eligible tokens by decorator auth shape and token-level good_at
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

### Managed Auth

Use `scripts/oauth_setup.py` for OAuth intake and refresh. Runtime clients
select eligible credentials through decorator-declared auth metadata and the
config-backed OAuth app catalog.

### Add an Account

```bash
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email user@yandex.ru --account alex --app mail-readonly
```

This prints the app approval URL, verifies the returned token, and creates or
reuses the verified account alias through managed auth.

### Generate a Token

```bash
# Recommended: default preconfigured app from config.skill.json, ready approval link
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email user@yandex.ru --account alex --app mail-readonly

# Recommended: choose a non-default preconfigured app variant
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email user@yandex.ru --account alex --app disk-full
```

Recommended flow:

- keep the checked-in app catalog in `config.skill.json` under `oauth_apps.catalog`
- choose app IDs explicitly with `--app`
- custom `--client-id --scope ...` tokens create or reuse an agent-local
  `oauth_apps.catalog` entry in `{data_dir}/config.agent.json`
- Yandex OAuth tokens are assumed to carry the full scope set configured on
  the app that issued the token; runtime does not model per-token scope
  narrowing
- the generated URL omits `scope=` by default and relies on the OAuth app's baked-in permissions

Current-used API methods declare auth directly in code through
`@yandex_api_method(method_id, public=True | one_of=[...] | all_of=[...])`.
Capability JSON files are development/audit inputs only. Normal runtime calls
use decorator metadata, managed-auth `client_id` bindings, and config-backed app
scope declarations.

### Auth Feedback Categories

Provider status, error code, and message remain the primary error payload.
Agents may additionally use these derived categories for remediation:

- `missing_or_invalid_credentials`: no token, expired token, rejected token, or
  protocol credential failure
- `missing_scope_or_wrong_app`: generic OAuth `403 ForbiddenError` after a
  decorated method selected a candidate token
- `account_or_org_policy_blocked`: post-auth provider policy, tariff, or org
  denial, such as Telemost `OrganizationSettingsAccessForbidden`
- `missing_resource_or_fixture`: protected API reached, but the requested
  object, path, message, or principal is absent
- `request_validation_failed`: protected API reached, but request shape or
  business validation failed
- `transient_or_unknown`: transport, rate-limit, server, or ambiguous failure

Only `403 ForbiddenError` becomes a token-rotation signal. Other provider
errors pass through with their exact payload and do not update token `good_at`
or `bad_at`.

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

## License

MIT
