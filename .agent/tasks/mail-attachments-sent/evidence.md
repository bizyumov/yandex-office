# Evidence

- Issue: https://github.com/bizyumov/yandex-office/issues/71
- Timestamp UTC: 2026-09-28T16:59:06.266531+00:00

- AC1: PASS: repeatable CLI --attachment and API attachments input; preserves basename, MIME type and bytes; validates/reads files before network activity.
- AC2: PASS: Date and Message-ID generated once; plain/HTML bodies, To/Cc/Reply-To preserved; Bcc is envelope-only.
- AC3: PASS: opt-in --save-sent/save_sent=True; managed full IMAP auth decorator, identity match, and existing Sent folder preflight before SMTP send.
- AC4: PASS: Sent append uses APPENDUID and UID read-back verification; missing/failed verification is unverified/failed, not success.
- AC5: PASS: smtp_status and sent_copy are separate; post-SMTP archival failure/partial/unknown states are explicit and never auto-resend.
- AC6: PASS: credential-free tests cover attachments, CLI wiring, auth scopes, preflight failures, SMTP failures/partial acceptance, APPEND errors/read-back failures, and docs.

## Commands

### compile

```text
$ python3 -m py_compile mail/scripts/send_email.py mail/scripts/test_send_email.py mail/scripts/test_send_attachments_sent.py
exit: 0

```

### targeted-tests

```text
$ uv run pytest mail/scripts/test_send_email.py mail/scripts/test_send_attachments_sent.py -q
exit: 0
..............................                                           [100%]
30 passed in 0.26s
```

### full-tests

```text
$ uv run pytest -q
exit: 0
........................................................................ [ 25%]
........................................................................ [ 50%]
........................................................................ [ 76%]
...................................................................      [100%]
=============================== warnings summary ===============================
forms/scripts/test_discover_forms.py::test_discover_forms_merges_registry_and_api_stats
  /opt/hermes/agents/one-ring/home/git/github/bizyumov/yandex-office/forms/scripts/discover_forms.py:232: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    "discovered_at": datetime.utcnow().isoformat() + "Z",

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
283 passed, 1 warning in 1.48s
```

### diff-check

```text
$ git diff --check && git diff --cached --check
exit: 0

```

### gitmark-index

```text
$ /opt/hermes/venv/bin/python /opt/hermes/shared/skills/ontoship/skills/kb-search/gitmark.py index
exit: 0
✓ index: 48 файлов · 767 чанков · 2 ссылок · trigram=on → .gitmark/index.db
```

### staged-secret-scan

```text
$ gitleaks protect --staged --redact --no-banner
exit: 0
4:59PM INF 1 commits scanned.
4:59PM INF scan completed in 71.3ms
4:59PM INF no leaks found
```
