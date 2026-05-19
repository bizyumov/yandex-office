# Evidence Bundle: calendar-time-preference-config

## Summary

- Overall status: PASS
- Frozen spec revision: 1
- Last updated: 2026-05-19

Calendar create-event now resolves one effective time context from CLI or local
`config.agent.json`, rejects root `config.skill.json` Calendar time preference,
and keeps timezone/offset conflict checks before Calendar or Telemost side
effects. A complete root `config.agent.schema.json` describes the current local
agent-config surface.

## Acceptance Criteria Evidence

### AC1. New agent-config schema exists

- Status: PASS
- Proof: `config.agent.schema.json` exists; `raw/schema-scan.txt` shows no prior
  schema artifact existed.

### AC2. Complete schema with descriptions

- Status: PASS
- Proof: `common/tests/test_agent_config_schema.py` checks the schema covers
  `mail`, `calendar`, `contacts`, `directory`, `forms`, and
  `oauth_apps.catalog`, omits persistent `accounts`, and requires descriptions
  for every defined schema property.

### AC3. Calendar time preference descriptions

- Status: PASS
- Proof: schema tests assert Calendar descriptions cover local preference,
  `config.skill.json` prohibition, CLI override, and matching timezone/offset
  rule.

### AC4. Example config

- Status: PASS
- Proof: `config.agent.example.json` includes `calendar.timezone` and no account
  inventory; `raw/json-parse.txt` and `raw/calendar-schema-pytest.txt` validate
  it.

### AC5. Local preference fallback

- Status: PASS
- Proof: `calendars/scripts/create_event.py` resolves config fallback only when
  no CLI time-context flag is provided; targeted Calendar tests cover local
  timezone fallback.

### AC6. CLI behavior preserved and extended

- Status: PASS
- Proof: targeted Calendar tests cover CLI timezone, CLI UTC offset, matching
  CLI pair acceptance, conflicting CLI pair rejection, CLI override of config,
  and unchanged no-config failure.

### AC7. Invalid config rejected before side effects

- Status: PASS
- Proof: targeted Calendar tests assert conflicting config pair, unknown
  timezone, malformed offset, and root `config.skill.json` time preference fail
  before Calendar or Telemost client initialization.

### AC8. Calendar doc is the agent-facing explanation

- Status: PASS
- Proof: `calendars/calendar.md` contains the timezone/UTC-offset explanation;
  `raw/skill-md-diff.txt` is empty, proving root `SKILL.md` was not changed.

### AC9. Release-facing docs

- Status: PASS
- Proof: `CHANGELOG.md` and `README.md` mention the local config preference and
  schema update.

### AC10. Tests cover required behavior

- Status: PASS
- Proof: `raw/calendar-schema-pytest.txt` reports `24 passed`; full pytest and
  regression also pass.

### AC11. Example validates against schema

- Status: PASS
- Proof: `common/tests/test_agent_config_schema.py` validates
  `config.agent.example.json` against the schema subset used by this repo;
  `raw/calendar-schema-pytest.txt` reports `24 passed`.

## Commands

- `raw/json-parse.txt`: JSON parse checks passed.
- `raw/build.txt`: Python compile passed.
- `raw/help-smoke.txt`: direct Calendar create-event help passed from `/tmp`.
- `raw/calendar-schema-pytest.txt`: `24 passed`.
- `raw/config-docs-pytest.txt`: `16 passed`.
- `raw/full-pytest.txt`: `176 passed, 1 warning`.
- `raw/regression.txt`: `159 passed, 1 warning`.
- `raw/audit.txt`: method-auth audit passed with existing warnings.
- `raw/diff-check.txt`: `git diff --check` passed.

## Known Gaps

None for the frozen acceptance criteria.
