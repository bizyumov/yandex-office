## Summary
- Add repeatable `--attachment` CLI support and `attachments` API input for the mail sender.
- Add opt-in `--save-sent` / `save_sent=True` with managed full-IMAP auth, Sent preflight, APPENDUID read-back verification, and retry-safe partial outcome reporting.
- Add credential-free SMTP/IMAP boundary tests plus Mail documentation and proof-loop evidence.

## Verification
- `python3 -m py_compile mail/scripts/send_email.py mail/scripts/test_send_email.py mail/scripts/test_send_attachments_sent.py`
- `uv run pytest mail/scripts/test_send_email.py mail/scripts/test_send_attachments_sent.py -q` — 30 passed
- `uv run pytest -q` — 283 passed, 1 warning
- `git diff --check && git diff --cached --check`
- `gitleaks protect --staged --redact --no-banner` — no leaks found
- GitMark index rebuilt

Closes #71
