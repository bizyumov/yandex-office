# Evidence: issue-13-17-mail-filter-profiles

## Summary

Current branch status after the final docs/code/spec pass:

- configured mail filters are flat under `mail.filters`
- legacy `mail.filters.sender` upgrades in-memory to the `telemost` filter
- `default` is reserved for ad-hoc runtime-only queries and is rejected as a configured filter key
- bare run executes all enabled configured filters across selected mailboxes
- `--filter NAME` runs exactly that named filter even if disabled
- raw CLI criteria without `--filter` run as one ad-hoc filter and search mailbox history by default
- persistent state is isolated by filter and mailbox in `state.json`
- saved mail lands in `incoming/<filter>/...` and persisted `meta.json` includes `filter` + `dir_relpath`
- non-ASCII sender/subject queries use Yandex-compatible `SEARCH UTF-8` plus sequence-to-UID remapping
- heavy dry-run result sets spill to an ephemeral file with a compact stdout summary

## Commands Run

### Focused tests

```bash
pytest -q mail/scripts/test_fetch_emails.py common/tests
```

Result:

```text
45 passed in 0.20s
```

### Repo regression suite

```bash
./scripts/test_regression.sh
```

Result:

```text
116 passed, 1 warning in 0.90s
```

Warning:

```text
forms/scripts/discover_forms.py:233 uses datetime.utcnow() (pre-existing deprecation warning)
```

### Syntax / import check

```bash
python3 -m compileall common scripts mail
```

Result:

```text
compileall completed without errors
```

### Patch hygiene

```bash
git diff --check
```

Result:

```text
clean
```

### PR metadata check

```bash
gh pr view 27 --repo bizyumov/yandex-office --json number,url,state,headRefName,baseRefName,title
```

Result:

```json
{"baseRefName":"main","headRefName":"issue-13-17-mail-filter-profiles","number":27,"state":"OPEN","title":"feat(mail): add named filters and ad-hoc fetch overrides","url":"https://github.com/bizyumov/yandex-office/pull/27"}
```

## Live Validation

Live commands were run from `/opt/openclaw/workspaces/velizar` against the real `work` mailbox.

### User-story searches

1. `--mailbox work --dry-run --sender 'Евгений Войтенков'`
   - PASS
   - `pending_total = 2`
   - newest timestamp: `2026-04-03T14:10:04Z`

2. `--mailbox work --dry-run --sender 'eurochem.ru'`
   - PASS
   - `pending_total = 178`
   - spilled output file created under `{data_dir}/latest-query/`
   - verified expected senders are present:
     - `KireevKV@eurochem.ru`
     - `LavrentevIA@eurochem.ru`
     - `Digital@eurochem.ru`

3. `--mailbox work --dry-run --subject 'Подготовка материалов по планам работ Консорциума на 2026г.'`
   - PASS
   - `pending_total = 3`

4. `--mailbox work --dry-run --subject 'СТО ИНТИ' --since-date 2025-01-01 --before-date 2026-01-01`
   - PASS
   - `pending_total = 12`
   - spilled output file created under `{data_dir}/latest-query/`

5. `--mailbox work --dry-run --sender 'inti.expert' --since-date 2026-03-12`
   - PASS
   - `pending_total = 9`
   - spilled output file created under `{data_dir}/latest-query/`

### State semantics and selector behavior

6. `--mailbox work --sender 'Евгений Войтенков' --num 1 --no-persist`
   - PASS
   - `fetched_total = 1`
   - `persist_state = false`
   - `state.json` SHA-256 unchanged before vs after run

7. `--filter assignment --mailbox work --from-uid 1 --num 1`
   - PASS
   - `fetched_total = 1`
   - `persist_state = false`
   - `state.json` SHA-256 unchanged before vs after run

8. `--mailbox nonexistent --dry-run`
   - PASS
   - fails with:
     - `Unknown mailbox "nonexistent". Available mailboxes: bdi, work`

9. bare run: `--mailbox work --dry-run`
   - PASS
   - reports all enabled configured filters in this workspace:
     - `telemost`
     - `assignment`

## Notes

- The live `velizar` workspace currently has a stale historical state bucket named `assignments` while the active config key is `assignment`. This is a workspace rename residue, not a repo codepath failure. Current runtime behavior still resolves the configured filters correctly.

## Files Touched

- `.agent/tasks/issue-13-17-mail-filter-profiles/spec.md`
- `README.md`
- `SKILL.md`
- `config.agent.example.json`
- `config.example.json`
- `mail/mail.md`
- `mail/scripts/fetch_emails.py`
- `mail/scripts/test_fetch_emails.py`

## Acceptance Criteria Status

- `AC1`: PASS
- `AC2`: PASS
- `AC3`: PASS
- `AC4`: PASS
- `AC4a`: PASS
- `AC5`: PASS
- `AC6`: PASS
- `AC7`: PASS
- `AC8`: PASS
- `AC9`: PASS
- `AC10`: PASS
- `AC11`: PASS
- `AC12`: PASS
- `AC13`: PASS
- `AC14`: PASS
