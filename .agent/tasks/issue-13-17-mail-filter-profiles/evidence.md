# Evidence: issue-13-17-mail-filter-profiles

## Summary

The mail skill now supports:

- named filter profiles under `mail.filters.profiles`
- legacy single-filter fallback via `mail.filters.sender`
- CLI filter selection and ad-hoc overrides
- per-filter cursor isolation inside `state.json`
- safe non-persistent one-off runs
- UTF-8 IMAP `SEARCH` fallback with sequence-to-UID mapping for Yandex IMAP

The implementation keeps regular cron usage backward-compatible while letting agents run mailbox-scoped or ad-hoc searches without editing config/state files.

## Commands Run

### Targeted mail tests

```bash
pytest -q mail/scripts/test_fetch_emails.py
```

Result:

```text
11 passed in 0.07s
```

### Repo regression suite

```bash
./scripts/test_regression.sh
```

Result:

```text
101 passed, 1 warning in 1.58s
```

Warning:

```text
forms/scripts/discover_forms.py:233 uses datetime.utcnow() (existing deprecation warning)
```

### Syntax / import check

```bash
python3 -m compileall common scripts mail
```

Result:

```text
passed
```

### Patch hygiene

```bash
git diff --check
```

Result:

```text
clean
```

### PR check

```bash
gh pr view 27 --repo bizyumov/yandex-office --json number,url,state,headRefName,baseRefName,title
```

Result:

```json
{"baseRefName":"main","headRefName":"issue-13-17-mail-filter-profiles","number":27,"state":"OPEN","title":"feat(mail): add filter profiles and ad-hoc fetch overrides","url":"https://github.com/bizyumov/yandex-office/pull/27"}
```

## Files Touched

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
- `AC5`: PASS
- `AC6`: PASS
- `AC7`: PASS
- `AC8`: PASS
- `AC9`: PASS
- `AC10`: PASS
- `AC11`: PASS
  - PR opened: https://github.com/bizyumov/yandex-office/pull/27
