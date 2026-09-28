# Frozen specification
Source: [issue #71](issue-reference.md). Scope: AC1-AC6 verbatim in that reference.

## Implementation contract
`EmailSender.send` accepts `attachments: list[str | Path] | None` and `save_sent: bool = False`. CLI repeatable --attachment and opt-in --save-sent. Sent is the existing Yandex folder named Sent; no folder creation, mailbox discovery, forwarding, or recipient changes.

Read all attachments and serialize MIME before SMTP transmission. Preflight IMAP managed full-access authentication, matching sender identity, and Sent selection. SMTP send occurs once. APPEND occurs only after at least one recipient is accepted. Save exact serialized outgoing MIME bytes; Bcc remains envelope-only. Cleanup failures never mask send results.

Results preserve existing fields and add smtp_status (accepted, partial, refused, unknown), sent_copy (status not_requested, verified, failed, unverified; folder/uid when known), and retry_safe=false after any SMTP attempt. Incomplete outcomes return status partial and CLI exit 2. SMTP refusal is status failed. Exceptions before SMTP are safe to correct and retry; no automated retry is added. Errors use bounded categories, not server text or credentials.

Verification uses APPENDUID, readonly Sent SELECT and UID BODY.PEEK fetch. Compare selected stable headers plus ordered leaf MIME type/filename/decoded-byte tuples with the composed message. Server-added Received headers are ignored. Missing APPENDUID returns unverified without SEARCH, append retry or resend.

## Proof plan
AC1-AC6: synthetic SMTP/IMAP boundary mocks exercising real MIME serialization and validation. Full repository pytest suite, compile check, diff/secret review; no real outbound email tests. Record baseline failures separately. Review latest diff and rerun targeted tests before PR. Verify live PR state and merge commit on main.

## Baseline and ownership
Existing canonical clone; clean starting tree on docs/issue-61-yo. New branch feat/mail-attachments-sent from origin/main. Shared installation is not edited. Current changes owned by this task: sender, sender tests, Mail docs, capability metadata if required, and this task directory.
