# feat(mail): support attachments and verified Sent copies

https://github.com/bizyumov/yandex-office/issues/71

## Problem
The SMTP sender accepts body text but cannot attach local files or persist a Sent copy. Consumers must currently assemble MIME messages and perform IMAP APPEND outside the supported sender.

## Acceptance criteria
- AC1: Add repeatable `--attachment PATH` and `attachments` API input. Preserve basename, MIME type and bytes; unknown types use application/octet-stream. Validate and read every file before network activity.
- AC2: Generate Date and Message-ID once; preserve plain/HTML bodies, To/Cc/Reply-To and explicit Bcc envelope handling. Never expose Bcc in transmitted or archived headers.
- AC3: Add opt-in `--save-sent` / `save_sent=True` (default false for compatibility with SMTP-only accounts). Authenticate IMAP through managed OAuth with mail:imap_full, verify the same account identity and preflight the existing Sent folder before SMTP. Do not create or write INBOX.
- AC4: After SMTP acceptance, append one copy with attachments to Sent. Use APPENDUID for read-back verification; compare Message-ID, relevant headers and decoded MIME content, not raw server-added headers. Return folder, UID and verification state. Missing APPENDUID or failed verification must be reported as unverified, not success.
- AC5: Separate SMTP outcome from Sent outcome. A post-send archival failure must explicitly report that SMTP accepted the message and must not cause an automatic resend. Partial recipient acceptance and ambiguous SMTP transport failures must also be explicit. CLI returns structured outcomes and nonzero exit status for incomplete outcomes. Close connections on all paths.
- AC6: Add credential-free automated tests for attachments, CLI wiring, auth scopes, preflight failures, SMTP failures/partial acceptance, APPEND errors and read-back failures. Document usage and recovery without sending test messages to real recipients.

## Scope and privacy
No personal mailbox content, real addresses, production message IDs, attachment names, credentials or environment paths in issue, code fixtures, docs or PR. Use synthetic example.com fixtures. Folder browsing (#36) and general forwarding are out of scope; this change targets sender-side attachment composition and Sent persistence only.

## Comments
[]