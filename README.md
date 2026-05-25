# yandex-office

A collection of [agentskills.io](https://agentskills.io/specification)-compliant skills for working with Yandex platform services.

Current release:

- version: `2026.05.25`
- version file: `VERSION`
- cumulative release notes: `CHANGELOG.md`

2026.05.25 adds managed Mail SMTP send and tightens managed OAuth import behavior:

- `mail-smtp` is the configured OAuth app profile for SMTP send
- Mail SMTP send uses managed OAuth; app-password and IMAP-scope SMTP fallback
  paths are not production behavior
- Mail SMTP capability evidence is refreshed after live SMTP auth/send probes
- unknown OAuth `client_id` imports query Yandex online client metadata for
  scopes instead of asking agents to describe custom-token permissions; the
  detailed rules live in `references/yandex-office-extension.md`
- CAPTCHA JSON during client metadata lookup creates an explicit
  `scopes: ["unresolved"]` agent-local marker that managed auth must resolve
  from Yandex before actual use
- live verification covered fresh token onboarding, CLI SMTP send coverage, and
  reply/header roundtrip checks

## Versioning

`yandex-office` uses dated skill versions in `YYYY.MM.DD` format.

- current released version lives in `VERSION`
- cumulative downloader-facing notes live in `CHANGELOG.md`
- release procedure lives in `RELEASING.md`

## Sub-Skills

| Skill | Description |
|-------|-------------|
| [mail](mail/) | Mail / Почта: generic email fetcher via IMAP XOAUTH2 — saves emails to incoming/ |
| [calendars](calendars/) | Calendar / Календарь: CalDAV integration for Yandex Calendar — list/create/update events, find slots, Telemost binding |
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

Yandex Cloud infrastructure guidance moved to the private standalone
`yandex-cloud` skill repository.

This repository now covers the remaining shared Yandex 360 office service skills only.

## Shared Configuration

All Yandex sub-skills use the same two-level config:

- skill defaults in root `config.skill.json`
- local runtime overrides in `{data_dir}/config.agent.json`
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
<full-path-to-yandex-office>/scripts/test_regression.sh
```

CWD runtime `{data_dir}/config.agent.json`:

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
- `python3 <full-path-to-yandex-office>/mail/scripts/fetch_emails.py --filter <name>` runs exactly that named filter, even if it is disabled for bare runs
- `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --accounts list` is the primary token-backed account discovery helper
- `python3 <full-path-to-yandex-office>/mail/scripts/fetch_emails.py --account <alias>` runs Mail against the selected Yandex account
- raw CLI overrides such as `--sender` / `--subject` do not advance persistent cursors and search account history by default when no `--filter` is selected
- `--uid` is a one-message, non-persistent read
- sender and subject filters are literal IMAP substring matches; no extra query language is implemented
- large dry-run result sets spill into `{data_dir}/latest-query/`; the next spilled run replaces the previous artifact, so copy it elsewhere if you need to keep it

First account discovery runs `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --accounts list` from CWD. This bootstraps `./yandex-data` and prints managed account aliases only.

## Auth Task Routing

- Discover aliases: `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --accounts list` prints aliases only.
- Create/update a local handle: `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --account alex` prints `{"alias":"alex","apps":[]}` when no email or app-backed token is known.
- Record email on a handle: `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email user@yandex.ru --account alex` prints `{"alias":"alex","email":"user@yandex.ru","apps":[]}` until a token is imported.
- Check account app coverage: `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --account alex` prints configured app IDs such as `mail-readonly` or custom app labels such as `custom(scope1, scope2)`.
- Print an OAuth approval URL: `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --app mail-readonly`; include `--account alex` only as an optional hint when that alias is already known.
- Import a supplied token: `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --from-env YANDEX_ACCESS_TOKEN`.

Do not ask for email to print an OAuth URL. `--app` is an `oauth_apps.catalog`
profile; token import verifies identity and stores by verified Yandex identity.
For whole-package onboarding use `--app office-core`; `--email` and `--account`
are optional hints and may not match the verified token identity.

### Data Directory

Runtime data lives **outside** the repo at `{data_dir}/`:

```
{data_dir}/
├── incoming/           # mail writes here
├── state.json          # UID/date tracking keyed by filter and account
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

Important: for "what is new", always run `python3 <full-path-to-yandex-office>/mail/scripts/fetch_emails.py` first. Do not treat `archive/` or `meetings/` as the source of truth for new messages.

Disk note:

- organization-only sharing is live-verified for the documented `public_settings.accesses[].macros` payload
- `available_until` behaves as an absolute Unix timestamp; omitting it means infinite sharing
- metadata does not reliably echo ACLs back, so share verification depends on public-resource endpoint behavior

Telemost recording OAuth caveat:

- links that look public (`yadi.sk/d/...`) may still require OAuth
- with managed auth for the selected account alias: API may return a downloadable link
- without managed auth for that account: API may return `404` for an existing Telemost resource
- `HEAD` requests are not a reliable availability probe

Telemost calendar note:

- `python3 <full-path-to-yandex-office>/calendars/scripts/create_event.py` can create a new Telemost conference, bind an existing one with `--telemost-conference-id`, or reuse an already known join URL with `--telemost-link`.
- Every create-event call must have an effective time context from local agent config or `--timezone <IANA>` / `--utc-offset <Z|+HH:MM|-HH:MM>`.
- Existing-conference binding can apply `--telemost-access-level`, `--telemost-waiting-room`, and `--telemost-cohosts` before the Calendar event is written.

Each skill is self-contained and can be used independently.

## Telemost Meeting Directory Contract

`telemost` stores each meeting under:

`{data_dir}/meetings/{YYYY-MM}/{YYYY-MM-DD_HH-MM}_{account}_{MEETING_UID}/`

Where:

1. `YYYY-MM` is derived from first-seen meeting timestamp.
2. Meeting folder starts with local date/time prefix `YYYY-MM-DD_HH-MM`.
3. Date/time prefix is immediately followed by account tag (`alex`, `work`, etc.).
4. Folder always ends with meeting UID (`_{MEETING_UID}` or `_unknown`).
5. Folder routing is constrained by same-day wildcard candidate matching.

Processing semantics:

1. Emails inside each `meeting_uid` are processed in natural `imap_uid` order.
2. For each email event, resolver scans `YYYY-MM/YYYY-MM-DD_*-*_{account}_{meeting_uid}`.
3. If exactly one candidate exists, transcript/summary/metadata are appended there.
4. If no candidate exists, a new `YYYY-MM/YYYY-MM-DD_HH-MM_{account}_{meeting_uid}` directory is created.
5. If multiple same-day candidates exist, event processing fails fast (integrity error, no heuristic pick).
6. `meeting.meta.json.media_links` is append-unique (deduplicated, order preserved).
7. `meeting.meta.json` stores recording links only in `media_links` (no `video_url`/`audio_url` fields).

Migration for existing folders:

```bash
python3 <full-path-to-yandex-office>/telemost/scripts/migrate_meeting_dirs.py --dry-run
python3 <full-path-to-yandex-office>/telemost/scripts/migrate_meeting_dirs.py
```

## OAuth Setup

### Mental Model

```text
CWD
  -> bootstrap resolves absolute data_dir from $PWD/yandex-data
  -> {data_dir}/config.agent.json
     -> local app catalog overrides + service-specific settings

Skill config.skill.json
  -> oauth_apps.catalog marks the default app with `is_default: true`
  -> oauth_apps.catalog.<app_id> stores app name, client_id, and declared scopes

python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --app mail-readonly
  -> reads oauth_apps.catalog.<app_id>
  -> selects the configured OAuth client and permission bundle
  -> generates approval URL
  -> verifies the pasted token to recover Yandex identity + client_id
  -> creates or reuses the token file resolved from verified identity
  -> updates managed auth storage
  -> adds a local app catalog override only when the verified client_id is unknown

runtime clients
  -> call methods decorated with @yandex_api_method(...)
  -> join managed auth client_id bindings to config-backed app scopes
  -> choose eligible tokens by decorator auth shape and token-level good_at
```

### OAuth App Selector

Use `--app <app_id>` to request a configured OAuth application by catalog key.
Do not make raw scopes the primary choice in agent-facing docs or workflows.
Choose the account, sub-skill, and business task first; managed auth resolves
tokens and scope coverage internally.

Default/read apps:

- `mail-readonly`: Mail fetch/read.
- `disk-read`: Disk read/download.
- `calendar-user`: selected-account Calendar access.
- `contacts-default`: Contacts access.
- `telemost-default`: Telemost meeting access.
- `tracker-read`: Tracker search/read.
- `forms-read`: Forms export/read.
- `directory-read`: Directory lookup/read.

Write-capable variants stay separate: `mail-readwrite` for Mail IMAP mutation,
`disk-full`, `tracker-full`, `forms-full`, and `directory-full`. SMTP sending
uses `mail-smtp`.

Whole-package OAuth uses `office-core`: Mail read, Disk full, Calendar, and
Telemost. It does not cover Contacts, Tracker, Forms, or Directory.

To inspect stored coverage for an account, run
`python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --account <alias>`
and read `apps`. This creates or updates the local account handle, so use it
only after `--accounts list` proves the alias exists or when account setup is
intended.

### Managed Auth

Use `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --app <app_id>` to print an approval URL; add `--account <alias>` only as an optional hint when that alias is already known. After authorization, the script verifies the pasted token, stores it under the verified Yandex identity, and adds a local app catalog override only for unknown `client_id` values. Runtime clients select credentials through decorator-declared auth metadata and the config-backed app catalog. Low-level unknown-`client_id` resolution rules live in `references/yandex-office-extension.md`.

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
- If an OAuth app's permissions change later, refresh authorization through `yandex-office`.
- For mail fetching, prefer a read-only app covering `mail:imap_ro`.

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
