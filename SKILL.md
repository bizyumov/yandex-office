---
name: yandex-office
description: Shared Yandex skill pack for Mail, Disk, Telemost, Calendar, Contacts, Directory, Forms, and Tracker. Yandex Search and Yandex Cloud now live in separate standalone skill repos.
homepage: https://github.com/bizyumov/yandex-office
license: MIT
compatibility: Python 3.10+, per-skill dependencies, network access for Yandex APIs
metadata:
  author: bizyumov
  version: "2026.05.07"
  openclaw:
    emoji: "🟡"
    requires:
      bins:
        - python3
---

# yandex-office

Use this skill directory as `<full-path-to-yandex-office>` in commands below.

Yandex accounts belong to the human user. Assets are reachable through those
accounts. The user delegates asset-management tasks to the OpenClaw agent; the
agent uses `yandex-office` as executor, not owner or OAuth consent authority.

## Account-First Workflow

Follow exactly:

1. **Determine account**: run `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --accounts list`.
   It prints aliases only and bootstraps `./yandex-data` in CWD if needed. Use
   only a listed alias. If the needed alias is absent, stop the task and import
   that account through `yandex-office` under user authorization. Do not choose another.

2. **Determine sub-skill/service**:

| Sub-Skill | Description |
|-------|-------------|
| [calendar](calendar/calendar.md) | Calendar / Календарь: CalDAV integration for Yandex Calendar — list/create/update events, find slots, Telemost binding |
| [telemost](telemost/telemost.md) | Telemost / Телемост: process Telemost emails, manage real conferences, and admin Telemost org defaults |
| [mail](mail/mail.md) | Mail / Почта: generic email fetcher via IMAP XOAUTH2 — saves emails to incoming/, supports filters |
| [disk](disk/disk.md) | Disk / Диск: download files from Yandex Disk, upload files to Disk, and manage public or organization-only share links (Telemost links may require OAuth) |
| [contacts](contacts/contacts.md) | Contacts / Контакты: CardDAV integration for Yandex Contacts — fuzzy lookup, create/update contacts |
| [directory](directory/directory.md) | Directory / Директория: Yandex 360 Directory API — users, departments, groups, and org-aware identity data |
| [forms](forms/forms.md) | Forms / Формы: export form responses from Yandex Forms — download results as XLSX or JSON |
| [tracker](tracker/tracker.md) | Tracker / Трекер: manage tasks in Yandex Tracker — create, search, update issues, manage Agile boards |

3. **Run business task**: open the chosen sub-skill doc and run its command with `--account <alias>`.
   This root file is only the router; command syntax lives in sub-skill docs.

Account source of truth: `./yandex-data/auth/*.token` filenames, not config.

Do not inspect emails or token contents to choose an account. Do not start from
API calls, token handling, config crawling, or a sub-skill doc.

Auth request routing:

- OAuth URL: run `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --app <app_id>`; add `--account <alias>` only if already known. Never ask email for a link.
- Account handle: run `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --account <alias>` to create/read the alias; add `--email <email>` to record email on that alias. Output is compact JSON with `alias`, optional `email`, and `tokens`.
- Token import: run `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --from-env <ENV_VAR>`; verified identity decides storage.

## Typical Scenarios

Use this only after account and sub-skill are selected.

1. Scenario #1: create a Telemost meeting in the calendar.
   Entry point: `calendar/calendar.md` -> `### 2. Schedule a Meeting` ->
   `#### Create a New Telemost Meeting in Calendar`.

```text
Scenario #1: create a scheduled Telemost meeting
[<full-path-to-yandex-office>/calendar/scripts/create_event.py] -> [Telemost conference] -> [Calendar event with join_url]
```

2. Scenario #2: process Telemost transcripts.
   Entry point: `telemost/telemost.md` -> `### Process Telemost Transcripts`.
   Always fetch emails with the predefined `telemost` mail filter before processing.

```text
[<full-path-to-yandex-office>/mail/scripts/fetch_emails.py --filter telemost] -> incoming/telemost/
  -> [<full-path-to-yandex-office>/telemost/scripts/process_meeting.py] -> meetings/
                                      \-> [Disk] optional recording downloads
```

## Managed Auth and Extensibility

Use this section only when auditing or extending low-level Yandex API methods.
For workflow commands, resolve account first.

Runtime auth lives on decorated methods. A low-level method declares exactly one
auth shape: `@yandex_api_method(method_id, public=True)`,
`@yandex_api_method(method_id, one_of=[...])`, or
`@yandex_api_method(method_id, all_of=[...])`.
The wrapper reads that metadata, resolves eligible managed tokens from token
`client_id` plus app-config scopes, tries candidates ordered by token-level
`good_at`, marks a token GOOD only after a normal return, marks BAD only for
`403 ForbiddenError`, and raises blocked-method feedback before the API call
when no eligible candidate exists. Callers do not pass tokens.

To find the method declaration and auth shape:

1. Search `capabilities/methods.json`; it inventories 315 Yandex API methods.
   Use `classification` and `local_sources` to identify methods used by current
   code.
2. Read `capabilities/method-scope-map.json` for the proven `public`, `one_of`,
   or `all_of` auth shape, and `capabilities/matrix.json` for denial evidence.
3. Treat `capabilities/README.md` as the authoritative yandex-office reference
   for method IDs, classifications, generated map shape, and probe provenance;
   treat `references/yandex-office-auth-principles.md` as the auth-model
   reference for accounts, apps, scopes, tokens, and response authority.
4. Run `python3 capabilities/audit-method-auth.py`; the method must be declared
   exactly once and must match the generated scope map.

Example:

```python
@yandex_api_method("disk.resources.get.disk", one_of=["cloud_api:disk.read"])
def _api_get_resource(ctx: YandexApiContext, endpoint: str, path: str) -> dict:
    return request_json(ctx, "GET", endpoint, params={"path": path})
```

For public methods use a complete decorator such as
`@yandex_api_method("disk.public.resources.get", public=True)`. Use
`all_of=[...]` only when one token must contain every listed scope; use
`one_of=[...]` for alternative sufficient auth contexts.

Non-examples: do not add `token` parameters, bypass managed auth with raw-token
environment fallbacks or raw-token CLIs, wrap call sites in `auth_call(...)`,
maintain a parallel method-auth registry, add per-method `response.ok` / JSON /
`403` handling, or add service-specific HTTP subclasses.

Response handling is central. Low-level methods call `request_json()`; it sends
the context-bound request and raises the shared provider exceptions while
preserving provider status, error, message, and payload. Only `TokenRejected`
from `403 ForbiddenError` rotates candidate tokens. All other `YandexApiError`
payloads pass through unchanged and do not update
`good_at` / `bad_at`; agents may add derived feedback labels:
`missing_or_invalid_credentials`, `missing_scope_or_wrong_app`,
`account_or_org_policy_blocked`, `missing_resource_or_fixture`,
`request_validation_failed`, or `transient_or_unknown`.

## Migration Note

Yandex Search moved to the standalone `yandex-search-skill` repository:

- https://github.com/bizyumov/yandex-search-skill

Use that skill when you need Yandex Cloud Search API v2. This `yandex-office` meta-skill no longer includes search instructions.

Yandex Cloud infrastructure guidance moved to the private standalone `yandex-cloud` skill repository.

## Versioning

`yandex-office` uses dated skill versions in `YYYY.MM.DD` format.

- current released version lives in `VERSION`
- cumulative downloader-facing notes live in `CHANGELOG.md`
- maintainer release procedure lives in `RELEASING.md`

## License

MIT
