# Task Spec: calendar-time-preference-config

Status: `FROZEN`
Frozen revision: `1`
Frozen on: 2026-05-19

## Original Task Statement

Add `--timezone` or `--utc-offset` user preference in the agent config file.
The agent config schema must have proper description and the skill must have
instructions. Do not implement without explicit user approval.

## Approval Gate

The user approved implementation on 2026-05-19. Implementation must remain
inside this frozen spec.

## Current Repo Facts

- Calendar event creation currently requires exactly one explicit time context:
  `--timezone <IANA>` or `--utc-offset <Z|+HH:MM|-HH:MM>`.
- `create_telemost_event()` receives `timezone_name` and `utc_offset` directly
  from CLI args and raises when both or neither are present.
- Runtime config is loaded from root `config.skill.json` plus local
  `{data_dir}/config.agent.json`; local agent config overrides skill defaults.
- The shipped local agent config template is `config.agent.example.json`.
- Repo scan found no existing agent-config schema artifact. The only root
  config JSON files found are `config.agent.example.json`, `config.json`, and
  `config.skill.json`; no `config.agent.schema.json` exists.
- Calendar docs already use a `calendar` config section for local Calendar
  settings examples.

## Target Behavior

Agent config can provide a default Calendar event time context so ordinary
Calendar create-event calls do not need to repeat `--timezone` or `--utc-offset`.
The preference is local-agent state only. Root `config.skill.json` is prohibited
from storing `calendar.timezone` or `calendar.utc_offset`, because different
agents may need different local times.

Accepted local config shape:

```json
{
  "calendar": {
    "timezone": "Europe/Moscow"
  }
}
```

or:

```json
{
  "calendar": {
    "utc_offset": "+03:00"
  }
}
```

`timezone` is an IANA timezone name. `utc_offset` is a fixed offset in the
existing CLI format: `Z`, `+HH:MM`, or `-HH:MM`.

Only one effective time-context value is required across CLI and
`config.agent.json`. If both `timezone` and `utc_offset` are present in the same
source, they are allowed only when they match. For a timezone plus offset pair,
"match" means the timezone's UTC offset at the event start equals the fixed
offset. A conflicting pair fails before Calendar or Telemost side effects.

Effective precedence:

1. If a create-event CLI call passes `--timezone` or `--utc-offset`, validate
   the CLI-supplied pair if both flags are present. If the CLI pair is valid,
   the CLI value is the effective time context for that call.
2. CLI values override local config for that command. A CLI value may differ
   from `config.agent.json`; the CLI value takes precedence and is not an error.
3. If the CLI call passes neither flag, read `calendar.timezone` or
   `calendar.utc_offset` from local `runtime.agent_config` only.
4. If local config contains both `calendar.timezone` and `calendar.utc_offset`,
   validate that they match; fail only when they conflict.
5. If neither CLI nor local config provides a time context, keep the current
   failure:
   exactly one of timezone or UTC offset is required.
6. If root `config.skill.json` contains `calendar.timezone` or
   `calendar.utc_offset`, fail with a clear config error.

## Agent Config Schema Scope

Because no existing schema was found, this task must create a complete
`config.agent.schema.json` for the current `{data_dir}/config.agent.json`
surface. It must not be a Calendar-only fragment.

Complete means the schema describes every currently documented or runtime-used
persistent local agent-config section:

- root object purpose and the fact that it is local to one agent/data directory.
- `mail`:
  - `filters` map keyed by lowercase English schema keys.
  - filter fields: `sender`, `subject`, `since_date`, `before_date`,
    `enabled`.
  - `fetch.sleep_seconds`.
  - `output.max_inline_symbols` and `output.spill_dir`.
  - `since` and `state_file`.
- `calendar`:
  - existing documented settings: `default_calendar`, `business_hours.start`,
    `business_hours.end`, `slot_granularity_minutes`.
  - new `timezone` and `utc_offset` fields with the rules in this spec.
- `contacts`:
  - `default_addressbook`, `sync_on_startup`, `cache_ttl_seconds`,
    `fuzzy_match_threshold`.
- `directory`:
  - `cache_ttl_hours`, `default_per_page`, `search_fuzzy_threshold`.
- `forms`:
  - `state_file`, `default_format`, `export.poll_interval_seconds`,
    `export.max_wait_seconds`.
- `oauth_apps.catalog`:
  - local custom app entries keyed by app id.
  - app fields currently accepted or persisted by code/tests, including
    `client_id`, `scopes`, `name`, `app_name`, `service`, `is_default`, and
    `omit_scope_in_url`.

The schema must include descriptions for every top-level and nested user-facing
property it defines. `accounts` must not be presented as a supported persistent
agent-config setting; account aliases come from managed auth/token inventory.

## Acceptance Criteria

- AC1: A new root `config.agent.schema.json` exists because no existing
  agent-config schema was found.
- AC2: `config.agent.schema.json` is a complete schema for the current
  persistent local agent-config surface, not a Calendar-only fragment. It covers
  the sections listed in "Agent Config Schema Scope" and includes descriptions
  for every user-facing property it defines.
- AC3: The schema descriptions for Calendar time preference explain:
  - `calendar.timezone` is an IANA timezone default for Calendar event creation.
  - `calendar.utc_offset` is a fixed UTC offset default for Calendar event
    creation.
  - one effective value must exist via CLI or `config.agent.json`.
  - if both fields are present in the same source, they are accepted only when
    they match.
  - CLI `--timezone` / `--utc-offset` values override local config for a single
    command, including when the CLI value differs from config.
  - root `config.skill.json` must not store these fields.
- AC4: `config.agent.example.json` contains a valid example of the Calendar time
  preference without copying account inventory into the template.
- AC5: `calendars/scripts/create_event.py` uses the local agent preference only
  when neither CLI time-context flag is supplied.
- AC6: Existing explicit CLI behavior is preserved:
  - CLI `--timezone` still works.
  - CLI `--utc-offset` still works.
  - passing both CLI flags works only when the timezone and offset match.
  - passing both CLI flags with conflicting values fails before side effects.
  - a CLI value different from config is accepted and takes precedence.
  - passing neither CLI flag and having no config preference still fails.
- AC7: Invalid config is rejected before side effects:
  - both `calendar.timezone` and `calendar.utc_offset` present but conflicting.
  - unknown IANA timezone.
  - malformed UTC offset.
  - root `config.skill.json` stores `calendar.timezone` or
    `calendar.utc_offset`.
- AC8: `calendars/calendar.md` is the only skill document that contains
  agent-facing explanation of Calendar timezone/UTC-offset behavior. It explains
  where to set the preference, which field to choose, matching/precedence rules,
  why root `config.skill.json` is prohibited for this preference, and when to
  still pass explicit CLI flags.
- AC9: Release-facing docs mention the config preference change in
  `CHANGELOG.md`, with version metadata handled according to repo instructions
  only if this change is approved for a release.
- AC10: Tests cover config fallback, CLI override precedence, invalid config, and
  unchanged no-config failure.
- AC11: Tests or validation prove `config.agent.example.json` is valid against
  the new complete schema.

## Files Expected To Change After Approval

- `config.agent.schema.json` or the approved schema location if the user chooses
  a different schema artifact.
- `config.agent.example.json`.
- `calendars/scripts/create_event.py`.
- `calendars/scripts/test_create_event.py`.
- `common/config.py` only if a small shared helper is needed for root-config
  prohibition or config error handling.
- `calendars/calendar.md`.
- Root `SKILL.md` only for editing existing Calendar CLI examples, if any. No
  explanatory prose insertions or deletions are allowed in root `SKILL.md`; if
  it has no Calendar CLI examples, leave it unchanged.
- `README.md` and/or `references/config-data-and-tests.md` if needed to keep
  config documentation consistent.
- `CHANGELOG.md`, `VERSION`, and relevant metadata only if this approved task is
  released as a new dated skill version.

## Constraints

- Do not implement before explicit user approval.
- Preserve existing CLI flags and output JSON keys.
- Do not add a new CLI for editing config.
- Do not reintroduce raw tokens, account inventory, or OAuth state into
  `config.agent.example.json`.
- Do not add `calendar.timezone` or `calendar.utc_offset` to
  `config.skill.json`.
- Do not add or remove explanatory prose in root `SKILL.md`; Calendar
  timezone/UTC-offset explanation belongs only in `calendars/calendar.md`.
- Root `SKILL.md` changes are limited to editing existing Calendar CLI examples,
  if such examples exist.
- Keep the diff small; do not introduce broad config framework refactors.
- Preserve the rule that Calendar event creation needs exactly one effective
  time context after CLI/config precedence and match validation.

## Non-Goals

- No live Yandex API behavior changes beyond selecting the effective time
  context before event creation.
- No changes to Calendar listing, Contacts, Mail, Disk, Telemost conference
  create/update semantics, or OAuth app selection.
- No automatic timezone inference from locale, account email, Calendar server
  data, or Directory user objects.
- No support for multiple per-account time preferences in this task.

## Verification Plan

- `python3 -m json.tool config.agent.schema.json`
- `python3 -m json.tool config.agent.example.json`
- Schema validation for `config.agent.example.json` against
  `config.agent.schema.json` using a project-available validator or a small
  standard-library validation fallback if no validator dependency exists.
- `python3 -m py_compile calendars/scripts/create_event.py common/config.py`
- `python3 /opt/openclaw/shared/skills/yandex-office/calendars/scripts/create_event.py --help`
- `python3 -m pytest calendars/scripts/test_create_event.py -q`
- `python3 -m pytest common/tests/test_config_auth.py common/tests/test_docs.py -q`
- Targeted tests must prove CLI override of config, matching timezone/offset
  pairs, conflicting pair rejection, local `config.agent.json` fallback,
  prohibited `config.skill.json` fields, and unchanged no-config failure.
- `python3 -m pytest -q`
- `scripts/test_regression.sh`
- `git diff --check`
- `python3 /opt/openclaw/.codex/skills/repo-task-proof-loop/scripts/task_loop.py validate --task-id calendar-time-preference-config`

## Explicit Approval Needed

Before freeze, the user must approve or change these draft decisions:

- Config path: `calendar.timezone` / `calendar.utc_offset`.
- Schema artifact: new complete root `config.agent.schema.json`, since no
  existing schema artifact was found.
- Match semantics above, including how timezone/offset equivalence is evaluated
  at event start.
- No per-account preference in this task.
