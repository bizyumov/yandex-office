# Changelog

All public `yandex-office` skill releases use the `YYYY.MM.DD` version format.

## 2026.05.19

### Fixed

- Replaced the rejected import bootstrap detour with direct file-relative
  `sys.path.insert(...)` setup in the affected command, library, and test files.
- Removed `PYTHONPATH` re-exec bootstraps, `importlib.util` loading, and the
  unapproved standalone Calendar package split.
- Renamed the Calendar sub-skill directory to `calendars/` and restored normal
  `calendars.lib.client` imports to avoid Python standard-library `calendar`
  shadowing.
- Added a complete root `config.agent.schema.json` for local agent config and
  a local Calendar event time preference through `calendar.timezone` or
  `calendar.utc_offset`.
- Calendar create-event now accepts the local time preference when CLI
  `--timezone` / `--utc-offset` is omitted, keeps CLI override precedence, and
  rejects Calendar time preference in root `config.skill.json`.

### Changed

- Aligned `VERSION`, root skill metadata, touched sub-skill metadata, and README
  release summary to `2026.05.19`.
- Documented Calendar time-context instructions in `calendars/calendar.md`.
- Moved the low-level extension notes to
  `references/yandex-office-extension.md` and added the agent-config schema
  contract there.
- Marked legacy top-level Mail filter fields as deprecated in favor of
  `mail.filters.<name>`.

### Verification

- `python3 -m py_compile $(rg --files -g '*.py')`
- direct `--help` smoke tests for Calendar, Disk, Forms, Mail, OAuth, Telemost,
  and Tracker command entrypoints from outside the repo root
- `config.agent.schema.json` and `config.agent.example.json` JSON parse checks
- source scan confirming no `PYTHONPATH` re-exec, `importlib.util` loader usage,
  or rejected standalone Calendar package references
- `python3 -m pytest calendars/scripts/test_create_event.py -q`
- `python3 -m pytest common/tests/test_agent_config_schema.py -q`
- full `pytest` with one existing `datetime.utcnow()` deprecation warning
- `python3 capabilities/audit-method-auth.py`
- `git diff --check`

## 2026.05.18

### Fixed

- Integrated the still-valid PR #32 consultation provisioning fixes from Sergey
  Pimenov on top of current managed-auth architecture.
- Made Calendar Telemost event creation require explicit user time context via
  `--timezone` or `--utc-offset`, with UID reuse and Telemost link reuse for
  repeat provisioning runs.
- Preserved existing Calendar attachment upload behavior while allowing
  existing Telemost conferences to be updated before writing the Calendar event.
- Stopped Telemost conference create/update writes from doing implicit
  post-write reads; explicit `get_conference()` remains the read/hydration path.
- Taught Telemost processing to read Mail filter output under
  `incoming/<filter>/<email-dir>/meta.json` and to pass the processing runtime
  data directory into recording downloads.
- Replaced the Calendar list-events path's use of the deprecated `caldav`
  `date_search()` helper with the supported `Calendar.search()` surface while
  keeping the `calendar.caldav.report.date_search` capability id for the
  underlying CalDAV REPORT operation.

### Changed

- Extended the method-auth audit to fail on production `_call_api` usage and to
  print warnings when decorated API calls are hidden behind deep local wrappers.
- Aligned `VERSION`, root skill metadata, README release summary, and touched
  sub-skill metadata to `2026.05.18`.

### Verification

- `python3 -m pytest calendars/scripts/test_create_event.py -q`
- full `pytest` with one existing `datetime.utcnow()` deprecation warning
- `python3 capabilities/audit-method-auth.py`
- `git diff --check`

## 2026.05.16

### Fixed

- Completed PR 42 account/Mail/auth scope for #31, #40, and #48.
- Made `oauth_setup.py --accounts list` the agent-facing account discovery
  helper. It prints managed account aliases only, one per line.
- Made `oauth_setup.py --account <alias>` the compact account capability
  helper. It creates or updates the local account handle and prints JSON with
  `alias`, optional `email`, and `apps`.
- Added app coverage to account summaries. `apps` maps stored token `client_id`
  values to configured app IDs such as `mail-readonly` or custom labels such as
  `custom(scope1, scope2)`.
- Fixed `oauth_setup.py --email <email> --account <alias>` so it records email
  on the supplied alias instead of creating a suffixed alias.
- Separated OAuth link generation from account metadata. `oauth_setup.py --app
  <app_id>` prints an approval URL without requiring email.
- Simplified managed token import. `oauth_setup.py --from-env <ENV_VAR>` stores
  by verified Yandex identity; supplied `--email` / `--account` values are
  diagnostics, not storage authority.
- Added Mail `--account`, one-message `--uid`, dry-run `--extract-links`, and
  non-persistent ad-hoc sender/subject/date searches.
- Restored planned Calendar, Contacts, Directory, and Tracker command/API
  shapes as explicitly unimplemented contracts with tracking issues.

### Changed

- Updated root and sub-skill agent-facing docs to use account-first routing,
  app-aware account summaries, and full
  `python3 <full-path-to-yandex-office>/...` command paths.
- Reworked root `SKILL.md` into a first-read router with a top document map,
  no Markdown tables, current OAuth app selector, and a link to the low-level
  managed-auth extension reference.
- Aligned `VERSION`, root skill metadata, README release summary, and touched
  sub-skill metadata to `2026.05.16`.

### Verification

- `python3 capabilities/audit-method-auth.py`
- focused account/Mail/docs/runtime pytest suite
- full `pytest` with one existing `datetime.utcnow()` deprecation warning
- `scripts/test_regression.sh`
- `git diff --check`

## 2026.05.04

### Changed

- clarified root, Calendar, Forms, and Tracker documentation around managed-auth
  account aliases and OAuth app selection
- removed stale Calendar command examples that exposed internal data-dir
  placeholders instead of the normal current-CWD runtime model
- documented the supported managed-auth method declaration surface for agents
  extending Yandex API scripts

### Verification

- `python3 capabilities/audit-method-auth.py`
- focused GH41 pytest suite: 147 passed
- full `pytest`: 153 passed, 1 existing deprecation warning
- JSON parse, privacy scan, release metadata check, docs account-inventory
  scan, S1-S15 inspection, and `git diff --check`

## 2026.05.03

### Fixed

- routed Mail IMAP authenticate, select, search, and fetch runtime calls through
  `YandexApiContext` decorator dispatch instead of passing raw token arguments
  or bypassing decorated method auth
- routed Disk directory creation through the shared `request_json` helper while
  preserving idempotent 409 handling
- added shared non-JSON response handling for Calendar CalDAV event PUT so
  dispatch only marks tokens good after accepted response statuses
- skipped token entries with `bad_at` during candidate ordering and rejected
  token objects that contain both `good_at` and `bad_at`

### Changed

- Disk scripts now silently digest `YANDEX_DISK_TOKEN` into managed auth before
  operations, ignore it when that token is already stored for the selected
  account, and never use it as a raw Authorization fallback

### Verification

- `pytest common/tests/test_api_runtime.py disk/scripts/test_download.py calendars/scripts/test_create_event.py mail/scripts/test_fetch_emails.py`
- `python3 capabilities/audit-method-auth.py`

## 2026.04.26

### Changed

- moved account inventory to managed auth and kept agent config focused on app
  definitions and agent-specific settings
- added decorator-declared method auth metadata for current-used runtime API
  methods and a capability audit for decorator drift
- added shared decorator dispatch for method-aware token selection, token-level
  `good_at` / `bad_at`, and blocked-method feedback
- normalized managed credential records around verified `client_id` bindings and
  removed new writes of legacy service-token metadata
- converted legacy service token entries during stateless script runs that
  touch them, including explicit and dispatch-time `YANDEX_DISK_TOKEN` import
- centralized JSON response handling so only `403 ForbiddenError` rejects a
  token candidate; other provider errors pass through with exact payload data
- updated docs for token-backed accounts, config-backed app definitions,
  method decorators, feedback categories, and Disk env-token conversion

### Verification

- `pytest common/tests/test_api_runtime.py common/tests/test_config_auth.py common/tests/test_oauth_setup.py`
- `python3 capabilities/audit-method-auth.py`
- `python3 -m py_compile common/api.py common/auth.py common/config.py common/oauth_apps.py scripts/oauth_setup.py capabilities/audit-method-auth.py`

## 2026.04.20

### Changed

- extracted the Cloud sub-skill into the private standalone `yandex-cloud`
  skill repo and removed Cloud from the yandex-office sub-skill surface
- expanded Mail capability coverage from the fetcher path to the RFC-derived
  IMAP command surface, including session, mailbox lifecycle, message read,
  message mutation, and UID command variants
- added SMTP session command rows alongside SMTP send while preserving the
  `bizyumov@yandex.ru` recipient allowlist for live send probes
- updated the Mail probe to execute generic IMAP commands against temporary
  probe mailboxes and cache unreachable SMTP network results

### Findings

- Yandex IMAP accepted all tested IMAP commands with both `mail:imap_ro` and
  `mail:imap_full`, including mailbox and message mutation commands.
- SMTP remains `unclear_needs_retest` from this host because
  `smtp.yandex.com:465` is unreachable.

### Verification

- `python3 capabilities/probe.py --service mail`
- `python3 -m py_compile capabilities/probe.py capabilities/validate.py`

## 2026.04.19

### Changed

- added generated capability-matrix coverage for Calendar CalDAV, Contacts
  CardDAV, and Mail IMAP methods
- added generic capability probe execution for DAV requests, IMAP XOAUTH2, SMTP
  XOAUTH2, OAuth-account discovery, and inconclusive network failures
- recorded service-specific probe notes for Calendar, Contacts, and Mail in
  `capabilities/README.md`
- recorded protocol-level upstream sources for Calendar, Contacts, and Mail:
  Yandex endpoint/OAuth docs plus WebDAV, CalDAV, CardDAV, IMAP, SMTP, SMTP
  AUTH, and OAuth SASL RFCs
- added Calendar, Contacts/CardDAV, and SMTP endpoint configuration to
  `config.skill.json`

### Verification

- `python3 capabilities/probe.py --service calendar`
- `python3 capabilities/probe.py --service contacts`
- `python3 capabilities/probe.py --service mail`
- `python3 -m py_compile capabilities/probe.py capabilities/validate.py`
- JSON parse check for `methods.json`, `matrix.json`, `method-scope-map.json`,
  and raw probe artifacts

## 2026.04.15

### Changed

- replaced the shipped root config template with `config.skill.json`
- removed skill-root bootstrap copying into mutable `config.json` and kept `config.json` only as a legacy fallback during loading
- switched OAuth app planning to a single config-driven catalog under `oauth_apps.catalog`
- marked default preconfigured apps directly in catalog entries with `is_default: true`
- sorted the OAuth app catalog keys strictly alphabetically
- updated OAuth and Disk docs to reference the config-driven default-app model

### Fixed

- `oauth_setup.py` now verifies pasted tokens through `https://login.yandex.ru/info?format=json`
- token onboarding now binds tokens to accounts by verified token email and creates the account when none exists yet
- token onboarding now records returned `client_id` metadata and warns instead of hard-rejecting non-standard app matches
- custom app tokens can now be saved even when the operator skips the optional permissions note
- OAuth app selection no longer depends on hardcoded scope catalogs in code
- Disk scripts no longer depend on duplicated hardcoded read/write scope constants

### Verification

- `pytest common/tests/test_config_auth.py common/tests/test_oauth_setup.py`
- `python3 -m py_compile common/oauth_apps.py scripts/oauth_setup.py disk/scripts/download.py disk/scripts/upload.py disk/scripts/share.py`
- `rg -n "DEFAULT_SCOPES|default_scopes\\(|DISK_WRITE_SCOPES|DISK_READ_SCOPES|SERVICE_SCOPES|service_defaults"`

## 2026.04.10

### Changed

- established flat mail filter configuration under `mail.filters.<name>`
- reserved `default` for ad-hoc runtime-only mail queries
- upgraded legacy `mail.filters.sender` handling to the `telemost` filter
- documented the shared config flow: `config.json` -> `{data_dir}/config.agent.json` -> `state.json`
- documented the release policy for dated skill releases

### Fixed

- mail bare runs now execute all enabled configured filters
- `--filter NAME` now runs exactly that filter even if disabled
- ad-hoc mail queries now search mailbox history by default instead of inheriting a hidden stored cursor
- per-filter mail state is isolated by filter and mailbox
- saved mail output is separated under `incoming/<filter>/...`
- Yandex IMAP UTF-8 sender/subject searches now use `SEARCH UTF-8` with sequence-to-UID remapping
- heavy dry-run result sets now spill to an ephemeral file with an explicit retention warning

### Migration Notes

- configured mail filters must live directly under `mail.filters`
- `mail.filters.profiles` is removed
- configured filter key `default` must not be used
- use `telemost` as the legacy/base Telemost filter key

### Verification

- `pytest -q mail/scripts/test_fetch_emails.py common/tests`
- `./scripts/test_regression.sh`
- `python3 -m compileall common scripts mail`
- live mailbox checks against the real `work` mailbox
