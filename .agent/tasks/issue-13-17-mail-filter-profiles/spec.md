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

Introduce first-class filters under `mail.filters` while keeping legacy single-filter configs working:

- legacy config remains valid:
  - `mail.filters.sender`
- new config shape supports:
  - `mail.filters.<name>`
- each filter may define:
  - `sender`
  - `subject`
  - `since_date`
  - `before_date`
  - `enabled`

Filter key constraint:

- filter names are schema keys, not user-facing labels
- keys must use lowercase English letters, digits, and underscores, starting with a letter
- these keys are used for persistent state and `incoming/<filter>/` directory names

Backward compatibility rule:

- legacy top-level keys such as `mail.filters.sender` define the implicit `telemost` filter
- entries under `mail.filters` define peer filters; `default` is reserved for ad-hoc one-off runs and must not be a configured filter key
- bare runs execute all enabled filters
- `--filter NAME` executes exactly that named filter whether or not it is enabled for bare runs

### Filter selection and ad-hoc overrides

Add CLI support for:

- `--filter NAME`
- `--sender VALUE`
- `--subject VALUE`
- `--since-date DATE`
- `--before-date DATE`
- `--mailbox NAME`
- `--from-uid UID`
- `--no-persist`

Run modes:

1. No filter CLI arguments:
   - run all enabled configured filters across all selected mailboxes
2. `--filter NAME`:
   - run exactly that named filter, even if `enabled: false`
3. Raw CLI criteria (`--sender`, `--subject`, `--since-date`, `--before-date`) without `--filter`:
   - run one ad-hoc filter for the current invocation only

Ad-hoc overrides must not mutate config files.

### State model

Extend `state.json` to isolate cursors by filter while preserving old state:

- keep mailbox state nested by mailbox name
- add filter-aware buckets so each persistent filter has independent `last_uid` / `last_received_date`
- legacy pre-filter state should still be readable as the `telemost` filter state

Important constraint from `#13`:

- each named filter must have independent persistent state
- the implementation may satisfy that either with separate state files per filter or with a single `state.json` containing per-filter sections
- the chosen implementation must be explicit in docs and verification artifacts
- do not narrow this design choice in the spec without proving the resulting UX still matches the issue intent

### Persistence semantics

- `--no-persist` skips all state writes
- `--dry-run` keeps current non-persistent behavior
- `--from-uid` changes the UID floor for the current run
- whether `--from-uid` alone persists or implies non-persistent mode remains an open design point from `#17` until validated against the intended UX
- the implementation and docs must make this behavior explicit

Important product boundary:

- ad-hoc requests must not require manual state surgery to be useful
- `--from-uid` is a low-level control, not the only acceptable way to make ad-hoc searches work
- raw CLI overrides used without `--filter` must search mailbox history by default instead of inheriting a stored filter cursor
- verification must check real ad-hoc searches both with and without `--from-uid`
- sender and subject values are literal IMAP substring matches; no higher-level query language is implemented by this task
- `mail.fetch.sleep_seconds` must not slow dry-run search-only requests

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

### Heavy-output handling

Ad-hoc search output must remain LLM-efficient.

- if the rendered result payload would be too large for efficient direct assistant use, the command must save the detailed result set to a file instead of printing the whole payload to stdout
- the threshold must be configurable
- threshold unit is Unicode symbols / characters, not bytes
- default threshold: `2000` symbols
- stdout must still remain useful, for example by returning:
  - result count
  - newest / oldest timestamps when relevant
  - output file path
  - any lightweight summary needed to continue the conversation safely
- spill artifacts are ephemeral: the next spilled run replaces the previous artifact
- stdout must explicitly warn that the user should copy the file elsewhere if they want to keep it

Configuration requirement:

- add a mail-output setting in config for this threshold
- document the config key and default behavior in skill docs

### Wrapper script scope

`fetch.sh` remains the cron-safe wrapper. This task may document its lock behavior but does not need to redesign lock bypass semantics unless implementation details make a minimal wrapper change necessary.

### Verification discipline

Because `#17` is about real Yandex IMAP behavior, local tests are necessary but not sufficient.

- do not treat local/unit tests as proof of production correctness for UTF-8 search or UID remapping
- before claiming completion, run explicit live mailbox validations for the implemented CLI paths
- the task artifacts must include a reusable live-test checklist tied to the actual functions and options being changed

## Acceptance Criteria

### AC1
`mail/scripts/fetch_emails.py` supports named filters plus legacy single-filter config without breaking current cron-style usage.

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
- no CLI filter arguments runs all enabled configured filters
- `--filter NAME` runs only that named filter even if disabled for bare runs
- CLI raw criteria without `--filter` run one ad-hoc filter for the current invocation only
- CLI overrides filter values for the current run only when `--filter NAME` is present
- raw CLI overrides used without `--filter` start from mailbox history by default instead of inheriting a stored filter cursor
- no config files are modified during ad-hoc runs

### AC4
Persistent state is isolated per filter, while legacy state remains readable for existing setups.

### AC4a
Saved email output is separated by filter under `incoming/<filter>/...`, and saved `meta.json` includes the filter key so fetched mail can be distinguished after the fact.

### AC5
`--dry-run` and `--no-persist` never write state, and the final `--from-uid` persistence semantics are implemented exactly as documented and verified by live tests.

### AC6
ASCII sender search keeps backward-compatible email matching, and non-email sender fragments avoid duplicate identical `FROM` criteria.

### AC7
Non-ASCII search criteria work without `UnicodeEncodeError` by using the Yandex-compatible `SEARCH UTF-8` fallback and sequence-to-UID mapping.

### AC8
`--mailbox nonexistent` fails with a clear error and a list of valid configured mailboxes.

### AC9
Tests cover:
- named filter resolution
- legacy fallback behavior
- enabled-filter bare-run behavior
- per-filter state isolation
- `--from-uid` semantics
- `--no-persist` semantics
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

### AC12
Live validation proves that the real Yandex IMAP behavior matches the implemented CLI behavior for the key ad-hoc and persistent search scenarios, especially UTF-8 sender searches and UID remapping.

### AC13
Real user-story queries are supported, not just low-level flag combinations. At minimum this includes:
- latest email from a named sender
- emails from a sender domain
- emails in a named discussion / subject thread
- emails with subject text inside a date window
- emails from a sender domain inside a recent time window

### AC14
Heavy result sets are handled efficiently:
- when output exceeds the configured symbol threshold, detailed results are written to a file instead of emitted inline
- threshold is configurable in mail config
- default threshold is `2000` symbols
- threshold is measured in symbols / characters, not bytes
- stdout still returns a compact summary plus the saved file path
- stdout explicitly warns that the spilled file is ephemeral and should be copied elsewhere if it must be retained

## Verification plan

- targeted mail tests via `pytest -q mail/scripts/test_fetch_emails.py`
- repo regression entrypoint `./scripts/test_regression.sh`
- syntax/import check via `python3 -m compileall common scripts mail`
- patch hygiene via `git diff --check`
- final git diff review against `origin/main`
- explicit live mailbox validation checklist recorded in `live-tests.md`
- live tests must cover:
  - UTF-8 sender full-name search
  - UTF-8 sender fragment search
  - ASCII display-name search
  - email-address sender search
  - subject-only ad-hoc search
  - combined sender + subject search
  - mailbox selector behavior
  - `--from-uid` semantics
  - `--no-persist` semantics
  - named filter profile execution
  - legacy config fallback
  - real `SEARCH UTF-8` sequence-to-UID remapping

## Confirmed Live Bugs

These bugs were confirmed on 2026-04-09 against the real `work` mailbox in `/opt/openclaw/workspaces/velizar`.

### LB1: UTF-8 sender search returns zero matches despite real mailbox hits

Observed live test:

- query intent: latest email from `Евгений Войтенков`
- expected by manual mailbox header scan: latest message at `2026-04-03 17:10:04`
- actual script result with `--mailbox work --sender 'Евгений Войтенков' --from-uid 1 --dry-run`: zero matches

Root cause already isolated:

- direct Yandex IMAP `SEARCH UTF-8` returns matching sequence numbers
- current UTF-8 remap path fails to parse Yandex `FETCH (UID)` responses of the form:
  - `b'5131 (UID 5296)'`
- `_extract_uid()` currently expects tuple-oriented fetch response items and returns `None` for the real Yandex bytes-only response shape
- result: all UTF-8 hits are dropped before they become UIDs

Impacted acceptance criteria:

- `AC7`
- `AC12`

Current branch status:

- fixed on the working branch
- live re-test now returns `2` matches for `Евгений Войтенков`
- newest timestamp now matches the manually verified email at `2026-04-03T14:10:04Z`

### LB2: UTF-8 subject search returns zero matches despite known discussion hits

Observed live test:

- query intent: discussion `Подготовка материалов по планам работ Консорциума на 2026г.`
- expected result from the test note: `3 emails`
- actual script result with `--mailbox work --subject 'Подготовка материалов по планам работ Консорциума на 2026г.' --from-uid 1 --dry-run`: zero matches

Status:

- this is consistent with the same UTF-8 remap failure as `LB1`
- treat it as a separate user-visible bug because it breaks non-ASCII subject search, not just non-ASCII sender search

Impacted acceptance criteria:

- `AC7`
- `AC12`

Current branch status:

- fixed on the working branch
- live re-test now returns the expected `3` discussion emails for:
  - `Подготовка материалов по планам работ Консорциума на 2026г.`

### LB3: Dry-run header fetch can drop individual matches in ASCII domain scans

Observed live test:

- query intent: emails from domain `eurochem.ru`
- actual script result with `--mailbox work --sender 'eurochem.ru' --from-uid 1 --dry-run`:
  - returned many matches
  - but emitted a live warning:
    - `Dry-run header fetch failed for UID 3672: 'int' object has no attribute 'decode'`

Why this matters:

- the command still returned results, but dry-run is not robust across all matching messages
- at least one matched email was skipped or partially failed during header fetch
- this is a separate bug from the UTF-8 remap issue because the query itself is ASCII and produced matches

Required follow-up:

- isolate the exact failing dry-run path for `FETCH` header retrieval / decoding
- add a regression test once the real response shape is understood

Impacted acceptance criteria:

- `AC9`
- `AC12`

Current branch status:

- fixed on the working branch
- live re-test for `eurochem.ru` returns `178` matches
- no dry-run warning was emitted in the latest rerun

### LB4: Subject-in-date-window lookup was previously unverified as a user story

Observed live test:

- query intent: emails with subject containing `СТО ИНТИ` in 2025
- actual script result with `--mailbox work --subject 'СТО ИНТИ' --since-date 2025-01-01 --before-date 2026-01-01 --from-uid 1 --dry-run`:
  - zero matches

Current branch status:

- resolved by live validation
- user reran:
  - `СТО ИНТИ` in 2025: pass
  - `СТО ИНТИ` in 2026: pass
- this path is now considered covered as a real user story

### LB5: Raw ad-hoc queries still inherit the stored filter cursor

Observed live re-test:

- query intent: run the five user-story lookups as actual ad-hoc CLI requests, without `--from-uid`
- actual results before this fix:
  - `--mailbox work --sender 'Евгений Войтенков' --dry-run`: zero matches
  - `--mailbox work --sender 'eurochem.ru' --dry-run`: only the newest post-cursor match
  - `--mailbox work --sender 'inti.expert' --since-date 2026-03-12 --dry-run`: zero matches

Why this matters:

- ad-hoc queries were already non-persistent, but they were still being constrained by the active filter cursor
- this violated the intended user-story behavior and made normal ad-hoc lookups depend on hidden state
- users had to add `--from-uid 1` to get trustworthy history searches, which the corrected spec explicitly rejects as the default UX

Impacted acceptance criteria:

- `AC3`
- `AC13`

Current branch status:

- fixed on the working branch
- raw CLI overrides used without `--filter` now search mailbox history by default
- named filter runs still keep their per-filter cursor semantics

## Scenario Requirements From Live User Stories

These requirements are derived from the five real mailbox queries recorded in `live-tests.md`. They describe what the finished feature must do for actual user-facing requests.

### SR1: Named-sender lookup

For a request like:

- `Get latest email from "Евгений Войтенков"`

the implementation must:

- return at least one matching email when such mail exists
- expose the newest matching timestamp correctly
- work with non-ASCII sender display names on real Yandex IMAP
- not require manual state rollback or config editing
- not require `--from-uid 1` just to bypass hidden cursor state

### SR2: Domain sender lookup

For a request like:

- `Get emails from domain "eurochem.ru"`

the implementation must:

- return emails from that domain as a usable result set
- include expected senders such as `KireevKV@eurochem.ru`, `LavrentevIA@eurochem.ru`, and `Digital@eurochem.ru` when they exist
- avoid dropping matches because of dry-run header decoding failures
- be operationally usable for large result sets
- work as an ad-hoc query without requiring a manual cursor override

### SR3: Discussion / thread lookup by subject text

For a request like:

- `Get emails in discussion "Подготовка материалов по планам работ Консорциума на 2026г."`

the implementation must:

- find discussion emails by subject text on real mailbox data
- support non-ASCII subject values
- return the expected count or at least a trustworthy result list when such discussion mail exists

### SR4: Subject lookup within a date window

For a request like:

- `Get emails with subject containing "СТО ИНТИ" in 2025`

the implementation must:

- support combining subject criteria with a date window
- make the time-window behavior explicit and correct
- work as a real lookup flow, not only as a low-level CLI combination that is unverified in practice
- document clearly that the subject text is matched as a literal substring via IMAP SEARCH, with no extra query language semantics

### SR5: Domain lookup within a recent time window

For a request like:

- `Get emails from domain "inti.expert" in the last 4 weeks`

the implementation must:

- support sender-domain filtering with date constraints
- return recent matches correctly on real mailbox data
- expose enough result metadata to confirm the output is right
- work without requiring `--from-uid` to escape stored filter state

### SR6: Broad-result queries stay operationally usable

For requests that may return many matches, such as:

- `Get emails from domain "eurochem.ru"`

the implementation must:

- avoid flooding stdout with an oversized payload
- detect when the rendered result set is too large for efficient assistant use
- save the detailed result set to a file when it crosses the configured symbol threshold
- return a compact summary and the saved file path so the next step can inspect the file directly
- keep only the latest spilled artifact by default, and tell the user to copy it elsewhere if they want to retain it

## Non-goals

- redesigning the shared runtime config loader
- changing the workspace/bootstrap data-dir model from issue `#21`
- replacing the cron wrapper lock strategy with a new concurrency system
- introducing write-side changes to mail processing output format
