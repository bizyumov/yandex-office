# Task Spec: issue-13-17-mail-filter-profiles

## Metadata
- Task ID: issue-13-17-mail-filter-profiles
- Created: 2026-04-09T00:00:00Z
- Repository root: /opt/openclaw/shared/skills/yandex-office
- Working branch: issue-13-17-mail-filter-profiles
- Upstream issues:
  - https://github.com/bizyumov/yandex-office/issues/13
  - https://github.com/bizyumov/yandex-office/issues/17
- Final deliverable: GitHub pull request against `bizyumov/yandex-office`

## Context

The current `mail` skill is still structured as a single cron-oriented fetcher:

- one global `mail.filters.sender`
- one mailbox-scoped cursor namespace in `state.json`
- no CLI filter/profile selection
- no safe ad-hoc cursor behavior
- IMAP search path assumes ASCII criteria and `UID SEARCH`

Issue `#13` asks for multiple named filters with per-filter state isolation and ad-hoc execution. Issue `#17` deepens that request with concrete CLI flags, mailbox selection, UTF-8 IMAP SEARCH fallback behavior, and explicit non-persistent one-off runs. Issue `#17` also states the two features should compose.

## Current observed code surfaces

- `mail/scripts/fetch_emails.py`
  - single global sender lookup from `mail.filters.sender`
  - state keyed only by `state["mailboxes"][mailbox_name]`
  - `_search_emails()` always uses `conn.uid("SEARCH", None, *criteria)`
  - CLI only exposes `--num`, `--verbose`, `--dry-run`, `--data-dir`
- `mail/scripts/fetch.sh`
  - hard PID lock for cron usage
- `mail/scripts/test_fetch_emails.py`
  - currently covers dry-run header collection and global `--num`
- docs/config
  - `mail/mail.md`, `README.md`, `SKILL.md`, `config.example.json`, `config.agent.example.json`

## Design intent

Implement a combined mail-filter upgrade that solves both issues in one cohesive model.

### Filter model

Introduce named filter profiles under `mail.filters` while keeping legacy single-filter configs working:

- legacy config remains valid:
  - `mail.filters.sender`
- new config shape supports:
  - `mail.filters.default`
  - `mail.filters.profiles.<name>`
- each profile may define:
  - `sender`
  - `subject`
  - `since_date`
  - `before_date`

Backward compatibility rule:

- if `mail.filters.profiles` is absent, current `mail.filters.sender` is treated as the implicit default profile

### Profile selection and ad-hoc overrides

Add CLI support for:

- `--filter NAME`
- `--sender VALUE`
- `--subject VALUE`
- `--since-date DATE`
- `--before-date DATE`
- `--mailbox NAME`
- `--from-uid UID`
- `--no-persist`

Resolution order:

1. CLI explicit filter selection / overrides
2. merged `config.agent.json`
3. root `config.json`
4. legacy fallback `mail.filters.sender`

Ad-hoc overrides must not mutate config files.

### State model

Extend `state.json` to isolate cursors by filter profile while preserving old state:

- keep mailbox state nested by mailbox name
- add filter-aware buckets so each persistent profile has independent `last_uid` / `last_received_date`
- legacy pre-profile state should still be readable as the default filter state

For this task, choose a single shared `state.json` with per-filter sections rather than separate state files per profile. This satisfies the “separate state” requirement without multiplying files or changing the top-level runtime contract.

### Persistence semantics

- `--no-persist` skips all state writes
- `--dry-run` keeps current non-persistent behavior
- `--from-uid` implies one-off execution and therefore must not persist state, even if `--no-persist` is omitted

This resolves `#17`’s open question in favor of the safer default.

### IMAP search behavior

Support richer criteria and UTF-8 fallback:

- ASCII-only criteria keep current `UID SEARCH` path
- any non-ASCII criterion must use `SEARCH UTF-8` with byte-encoded criteria values
- when using `SEARCH UTF-8`, map sequence numbers back to UIDs via `FETCH (UID)`
- sender behavior:
  - if value contains `@`, keep local/domain split for backward-compatible email matching
  - if value does not contain `@`, use a single `FROM "<value>"` criterion

### Mailbox selection

- `--mailbox NAME` restricts fetch to one configured account
- invalid names fail fast with a clear error listing available mailbox names

### Wrapper script scope

`fetch.sh` remains the cron-safe wrapper. This task may document its lock behavior but does not need to redesign lock bypass semantics unless implementation details make a minimal wrapper change necessary.

## Acceptance Criteria

### AC1
`mail/scripts/fetch_emails.py` supports named filter profiles plus legacy single-filter config without breaking current cron-style usage.

### AC2
CLI supports:
- `--filter`
- `--sender`
- `--subject`
- `--since-date`
- `--before-date`
- `--mailbox`
- `--from-uid`
- `--no-persist`

### AC3
CLI/config filter resolution composes correctly:
- selected profile provides defaults
- CLI overrides profile values for the current run only
- no config files are modified during ad-hoc runs

### AC4
Persistent state is isolated per filter profile, while legacy state remains readable for existing setups.

### AC5
`--dry-run` and `--no-persist` never write state, and `--from-uid` implicitly behaves as non-persistent one-off execution.

### AC6
ASCII sender search keeps backward-compatible email matching, and non-email sender fragments avoid duplicate identical `FROM` criteria.

### AC7
Non-ASCII search criteria work without `UnicodeEncodeError` by using the Yandex-compatible `SEARCH UTF-8` fallback and sequence-to-UID mapping.

### AC8
`--mailbox nonexistent` fails with a clear error and a list of valid configured mailboxes.

### AC9
Tests cover:
- named profile resolution
- legacy fallback behavior
- per-filter state isolation
- `--from-uid` / `--no-persist` semantics
- mailbox filtering and invalid mailbox handling
- UTF-8 search fallback path
- sender criterion construction for address vs display-name fragments

### AC10
Docs and examples are updated in:
- `mail/mail.md`
- `README.md`
- `SKILL.md`
- `config.example.json`
- `config.agent.example.json`

### AC11
The task ends with verification artifacts (`evidence.md`, `evidence.json`, raw command outputs as needed) and a PR-ready branch for `bizyumov/yandex-office`.

## Verification plan

- targeted mail tests via `pytest -q mail/scripts/test_fetch_emails.py`
- repo regression entrypoint `./scripts/test_regression.sh`
- syntax/import check via `python3 -m compileall common scripts mail`
- patch hygiene via `git diff --check`
- final git diff review against `origin/main`

## Non-goals

- redesigning the shared runtime config loader
- changing the workspace/bootstrap data-dir model from issue `#21`
- replacing the cron wrapper lock strategy with a new concurrency system
- introducing write-side changes to mail processing output format
