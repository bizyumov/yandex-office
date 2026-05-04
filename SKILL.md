---
name: yandex-office
description: Shared Yandex skill pack for Mail, Disk, Telemost, Calendar, Contacts, Directory, Forms, and Tracker on this OpenClaw host. Yandex Search and Yandex Cloud now live in separate standalone skill repos.
homepage: https://github.com/bizyumov/yandex-office
license: MIT
compatibility: Python 3.10+, per-skill dependencies, network access for Yandex APIs
metadata:
  author: bizyumov
  version: "2026.05.04"
  openclaw:
    emoji: "🟡"
    requires:
      bins:
        - python3
---

# yandex-office

A collection of [agentskills.io](https://agentskills.io/specification)-compliant skills for working with Yandex user account assets. Like `gog`, but for Yandex.

## Reading Map

- Need the right sub-skill doc first? See `Sub-Skills and Where To Read Them`, lines 31-42 below.
- Need to onboard the user or add another account/token? See `Onboarding`, lines 44-114 below.
- Need to choose what the skill pack can do? See `Typical Scenarios`, lines 116-138 below.
- Need to extend managed auth? See `Managed Auth and Extensibility`, lines 140-196 below.
- Need to know where Yandex Search or Yandex Cloud went? See `Migration Note`, lines 198-206 below.
- Need release/version pointers? See `Versioning`, lines 208-214 below.
- Need details on config schema, data structure or automated tests? See `references/config-data-and-tests.md`.

## Sub-Skills and Where To Read Them

| Sub-Skill | Description |
|-------|-------------|
| [mail](mail/mail.md) | Mail / Почта: generic email fetcher via IMAP XOAUTH2 — saves emails to incoming/, supports filters |
| [calendar](calendar/calendar.md) | Calendar / Календарь: CalDAV integration for Yandex Calendar — list/create/update events, find slots, Telemost binding |
| [contacts](contacts/contacts.md) | Contacts / Контакты: CardDAV integration for Yandex Contacts — fuzzy lookup, create/update contacts |
| [directory](directory/directory.md) | Directory / Директория: Yandex 360 Directory API — users, departments, groups, and org-aware identity data |
| [telemost](telemost/telemost.md) | Telemost / Телемост: process Telemost emails, manage real conferences, and admin Telemost org defaults |
| [disk](disk/disk.md) | Disk / Диск: download files from Yandex Disk, upload files to Disk, and manage public or organization-only share links (Telemost links may require OAuth) |
| [forms](forms/forms.md) | Forms / Формы: export form responses from Yandex Forms — download results as XLSX or JSON |
| [tracker](tracker/tracker.md) | Tracker / Трекер: manage tasks in Yandex Tracker — create, search, update issues, manage Agile boards |

## Onboarding

### First run

**IMPORTANT:** Running scripts with `cd` outside CWD **WILL AUTOMATCALLY FAIL**; use the default CWD or pass `--data-dir`.

You need to onboard the skill first. To onboard `yandex-office` skill pack for the first time:

1. Check `./yandex-data` in the current working directory, do not `cd`.
2. If it does not exist, run `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py` from that CWD with no extra arguments.
3. Let `scripts/oauth_setup.py` create bootstrap files and directories.

### Adding Yandex accounts

You need to know which accounts the assets are bound to. To add a user Yandex account:

1. Stay in the CWD.
2. Initialize the account alias with the provided email:

```bash
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email <email> --account <alias>
```

### Issuing OAuth App Tokens

You need actual OAuth tokens to access user assets. When the account already exists and the user wants you to gain access:

1. Stay in the CWD.
2. Help the user choose the app ID based on the desired capability. Use the read/default app unless the user explicitly requires write permissions.

| Capability | Default App ID | Write-Capable App ID |
|------------|----------------|-----------------------|
| Mail read/fetch | `mail-readonly` | `mail-readwrite` |
| Disk read/download | `disk-read` | `disk-full` |
| Calendar | `calendar-user` | same |
| Contacts | `contacts-default` | same |
| Telemost meetings | `telemost-default` | same |
| Tracker read/search | `tracker-read` | `tracker-full` |
| Forms export/read | `forms-read` | `forms-full` |
| Directory lookup/read | `directory-read` | `directory-full` |

3. Offer `office-core` convenience bundle app when the user asks for multiple capabilites covering Mail, Disk, Calendar, and Telemost.

4. Upon user approval, run the exact CLI command to obtain the URL for OAuth authorization:

```bash
# replace 'mail-readonly' with the appropriate app ID from the table above
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email <email> --account <alias> --app mail-readonly
```

5. Provide a URL to the user and ask to complete OAuth in the browser. The same terminal command then waits at this exact input line:

```text
Paste the access_token here:
```

6. Paste the returned `access_token` at that hidden-input line and press Enter. `scripts/oauth_setup.py` verifies the pasted token and updates managed auth.

7. If you already have the token value and you need a non-interactive import, run this exact CLI:

```bash
IFS= read -rsp 'Paste access_token: ' YANDEX_ACCESS_TOKEN
printf '\n'
export YANDEX_ACCESS_TOKEN
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --from-env YANDEX_ACCESS_TOKEN
unset YANDEX_ACCESS_TOKEN
```

In `--from-env` mode, the script verifies the bearer and uses the returned email and client ID for the managed-auth account and app binding.

**IMPORTANT:** instructions for token revocation are in the Onboarding.md file.

## Typical Scenarios

Use this section to answer "What can this skill pack do?" Start here, then
read the named sub-skill entry point before running the command.

1. Scenario #1: create a Telemost meeting in the calendar.
   Entry point: `calendar/calendar.md` -> `### 2. Schedule a Meeting` ->
   `#### Create a New Telemost Meeting in Calendar`.

```text
Scenario #1: create a scheduled Telemost meeting
[calendar/scripts/create_event.py] -> [Telemost conference] -> [Calendar event with join_url]
```

2. Scenario #2: process Telemost transcripts.
   Entry point: `telemost/telemost.md` -> `### Process Telemost Transcripts`.
   Always fetch emails with the predefined `telemost` mail filter before processing.

```text
[mail/scripts/fetch_emails.py --filter telemost] -> incoming/telemost/
  -> [telemost/scripts/process_meeting.py] -> meetings/
                                      \-> [Disk] optional recording downloads
```

## Managed Auth and Extensibility

Use this section only when auditing or extending low-level Yandex API methods.
To add a Yandex account or import an OAuth token, follow `## Onboarding` in this
file, lines 44-114. To run a workflow command, open the named sub-skill doc.

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
