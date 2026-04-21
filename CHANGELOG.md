# Changelog

All public `yandex-office` skill releases use the `YYYY.MM.DD` version format.

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
