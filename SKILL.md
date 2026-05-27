---
name: yandex-office
description: Shared Yandex skill pack for Mail, Disk, Telemost, Calendar, Contacts, Directory, Forms, and Tracker. Yandex Search and Yandex Cloud live in separate standalone skill repos.
homepage: https://github.com/bizyumov/yandex-office
license: MIT
compatibility: Python 3.10+, per-skill dependencies, network access for Yandex APIs
metadata:
  author: bizyumov
  version: "2026.05.26"
  openclaw:
    emoji: "🟡"
    requires:
      bins:
        - python3
---

# yandex-office

Use this skill directory as `<full-path-to-yandex-office>` in commands below.
Do not `cd` into the skill directory before running commands. CWD determines
`./yandex-data`; use full script paths from CWD, or pass `--data-dir`.

Aliases are the account handles passed to commands. Email is the verified
Yandex identity behind an alias. Apps, scopes, and tokens are defined in
`references/yandex-office-auth-principles.md`.

## Document Map

- (1-16) Frontmatter (metadata version 2026.05.26)
- (17-25) Opening Model
- (27-40) Document Map
- (42-47) Reference Map
- (49-75) Account-First Workflow
- (77-108) Account And OAuth Helper
- (110-135) OAuth App Selector
- (137-154) Token Handling
- (156-179) Full Authorization Workflow
- (181-214) Common Workflows
- (216-221) Extension Reference Link
- (223-232) Migration, Versioning, License

## Reference Map

- Auth model: `references/yandex-office-auth-principles.md`
- OAuth screen-code / PKCE flow: `references/oauth-screen-code-flow.md`
- OAuth screen-code testing pitfalls: `references/oauth-screen-code-testing-pitfalls.md`
- Config and data shape: `references/config-data-and-tests.md`
- Service overview: `references/yandex-service-reference.md`
- Service overview: `references/yandex-service-reference.md`
- Service overview: `references/yandex-service-reference.md`
- Service overview: `references/yandex-service-reference.md`
- Extension reference: `references/yandex-office-extension.md`

## Account-First Workflow

Run first:
`python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --accounts list`

If aliases print, choose only an exact listed alias. If no alias is suitable,
pause the business task and set up or import the account through `yandex-office`
under user authorization. If nothing prints, no account alias is configured in
this CWD yet; choose the minimum setup path from the user's request.

Then choose the sub-skill:
- Mail: `mail/mail.md`
- Calendar: `calendars/calendar.md`
- Telemost: `telemost/telemost.md`
- Disk: `disk/disk.md`
- Contacts: `contacts/contacts.md`
- Directory: `directory/directory.md`
- Forms: `forms/forms.md`
- Tracker: `tracker/tracker.md`

Calendar note: `calendar` is reserved by Python library so the dir was renamed
to `calendars`.

Run the business command from that sub-skill doc with `--account <alias>`.
No-arg `oauth_setup.py` is legacy/bootstrap troubleshooting, not the primary
onboarding path. The literal alias `list` is valid; discovery uses plural
`--accounts list`, while literal account use is `--account list`.

## Account And OAuth Helper

- List aliases:
  `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --accounts list`
- Create or update an account handle:
  `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --account <alias>`
- Create or resolve an alias from email:
  `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email <email>`
- Save email under a chosen alias:
  `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email <email> --account <alias>`
- Generate an OAuth URL:
  `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --app <app_id>`
- Import an environment token:
  `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --from-env <ENV_VAR>`

Do not use `--account <alias>` to test whether an alias exists. It creates or
updates the local account handle. Use it only when that is intended, or after
`--accounts list` already proved the alias exists.

`--account <alias>` prints compact JSON with `alias`, optional `email`, and
`apps`. `apps` maps each stored token `client_id` to a configured app ID such as
`mail-readonly` or `office-core`. Custom client IDs print as
`custom(scope1, scope2, ...)`.

`--email <email>` first reuses an existing alias whose token file already has
that email. If none exists, it derives a new alias from the email. Use
`--email <email> --account <alias>` only when the local alias must be explicit.

Maintenance:
- `--accounts delete --account <alias>` deletes one account token file.
- `--accounts reset` deletes all account token files. It is destructive; use
  only after an explicit user request.

## OAuth App Selector

Use the default/read app unless the user requests a write-capable operation or
explicitly approves broader access.

- Mail read/fetch: default `mail-readonly`; IMAP mutation/delete: `mail-readwrite`; SMTP send: `mail-smtp`.
- Disk read/download: default `disk-read`; write-capable `disk-full`.
- Calendar: `calendar-user`; default app already has operational coverage.
- Contacts: `contacts-default`; default app already has operational coverage.
- Telemost meetings: `telemost-default`; default app already has operational coverage.
- Tracker read/search: default `tracker-read`; write-capable `tracker-full`.
- Forms export/read: default `forms-read`; write-capable `forms-full`.
- Directory lookup/read: default `directory-read`; write-capable `directory-full`.

Whole package means `office-core`: Mail read, Disk full, Calendar, and Telemost.
It does not cover Contacts, Tracker, Forms, or Directory. For whole-package
OAuth, `--app office-core` is required. Email and account are optional hints and
may not match the verified token identity if the human authorizes while logged
into a different Yandex account.

Examples: `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --app office-core`
or `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --email <email> --account <alias> --app office-core`

To ensure an account covers a workflow, run `--account <alias>` and read `apps`.
For Calendar plus Telemost, acceptable coverage includes `office-core`, or both
`calendar-user` and `telemost-default`. Runtime API responses remain final truth.

## Token Handling

The user authorizes OAuth tokens. `yandex-office` verifies and stores them.
Never put an access token in visible command arguments, final text, logs, or
artifacts. In non-interactive tool execution, use `--from-env` for bearer
Warnings print to stderr; stdout is the resolved alias as one line.

For live tests and debugging of screen-code flow, preserve the pending registry
as evidence. Do not clear `{data_dir}/auth/oauth-code-flow.json`, regenerate
batches, or delete newly resolved aliases unless the user explicitly asks. When
reporting a completion attempt, include the exact command, complete non-secret
stdout/stderr, exit code, registry before/after, and account summaries. If the
user asks a code to land in a specific alias, pass `--account <alias>` on the
`--code-flow complete` command and verify the target alias afterwards; also
report any warning if managed import resolved and wrote a different alias. See
`references/oauth-screen-code-test-debugging.md`.

Prefer the Yandex screen-code authorization flow over asking the user to paste
an `access_token`: generate an authorization-code URL with PKCE, have the user
paste the short confirmation code, exchange it inside `oauth_setup.py`, then
import the returned bearer token through managed auth without printing it. A
direct CLI parameter such as `--code <confirmation-code>` is acceptable for the
second phase because the code is short-lived and single-use; do not force this
code through an environment variable. See
`references/oauth-screen-code-flow.md`.
See also `references/oauth-account-routing-pitfalls.md` before changing managed
OAuth alias routing or screen-code completion reports.

```bash
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --account <alias> --app <app_id> --code-flow start
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --account <alias> --code-flow complete --code <confirmation-code>
```

Keep all in-flight screen-code transactions in one registry file,
`{data_dir}/auth/oauth-code-flow.json`, not one file per authorization. For
For multiple pending links, do not ask the user to label codes by app/link/flow;
accept bare codes, complete them in the user's message order, and have the CLI
try pending entries in link issue order. In screen-code testing, the human may
deliberately send codes in any convenient order; do not force a reset or demand
exact link order unless they ask for a clean-room retest. Treat Yandex
`invalid_grant` / `Code has expired` / bad-code responses from one pending
entry as a non-match and continue trying later pending entries; only fail after
all pending entries have been tried.

When the user sends one or more bare confirmation codes in chat during an active
screen-code flow, treat that as an instruction to complete the pending OAuth
flows now. For a batch of codes, run `--code-flow complete` once per code and
record/report the command, stdout, stderr, and exit code for each code
separately; do not combine multiple completions in one shell command where a
later success can mask an earlier non-zero exit. Snapshot the pending registry
before the batch and after the batch, redacting `code_verifier` and token-like
fields, and verify the target account summary after successful completions.
When the user provides a concrete failed command/output for this flow, do not
paraphrase obvious facts back to them; inspect the implementation path, name the
exact defective branch/assumption, then patch and verify it.

When `--account <alias>` is supplied and no existing token file already uses
the verified email, write the token to that exact alias. Verified Yandex
identity/email is stored inside that alias's token file; it must not silently
derive a different alias from the verified email. If the verified email already
exists in another account file, keep using that existing account and warn about
the mismatch. Screen-code completion stdout must be a token-safe JSON work
report: operation, whether the token was processed/saved, requested account,
saved account, verified email, app id/client id, apps now present, and token
path. Warnings print to stderr.

When debugging OAuth/account-routing bugs, preserve the system invariant before
patching: first inspect the existing resolution order, then make the smallest
branch change. Correct order for managed token import is: existing verified-email
account wins; else explicit `--account`; else derive alias from verified email.
Do not “fix” by making CLI arguments override existing-account binding globally,
and do not remove existing mismatch warnings unless the user specifically asks.
If the user supplies command/output/interpretation, treat it as a bug report:
inspect the defective branch and patch it; do not restate the obvious or invent
new helper abstractions for one-off JSON reporting.

```bash
# In a real interactive shell; do not echo the token value.
IFS= read -rsp 'Paste access_token: ' YANDEX_ACCESS_TOKEN; printf '\n'
export YANDEX_ACCESS_TOKEN
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --from-env YANDEX_ACCESS_TOKEN
unset YANDEX_ACCESS_TOKEN
```

If the user deliberately sends a token in chat, treat it as current
user-provided secret input. Do not recover tokens from session logs and do not
edit token files by hand; use managed import.

## Screen-Code Testing Discipline

When testing `--code-flow` with a human sending short codes, preserve the pending
registry as evidence. Do not manually clear `{data_dir}/auth/oauth-code-flow.json`
or delete temporary token accounts until the user explicitly asks or smoke checks
are complete. Follow the user's account scope exactly: pass `--account <alias>`
only when they ask for that alias; omit `--account` when they say to complete
without specifying an account. During debugging, report the full JSON stdout from
`--code-flow complete` (including `requested_account`, `saved_account`, `app_id`,
`apps`, and `token_path`) instead of summarizing. A successful `token_saved: true`
proves import, not product API usability; verify relevant APIs before cleanup
when the goal is end-to-end authorization testing. See
`references/oauth-screen-code-testing-pitfalls.md`.

## Full Authorization Workflow

To authorize an account across ALL yandex-office sub-skills with maximum
permissions, generate OAuth URLs for this set of apps:

1. `office-core` — Mail (read), Disk (full), Calendar, Telemost
2. `mail-readwrite` — Mail IMAP mutation/delete
3. `mail-smtp` — Mail SMTP send
4. `contacts-default` — Contacts (read + modify)
5. `tracker-full` — Tracker (read + write)
6. `forms-full` — Forms (read + write)
7. `directory-full` — Directory (all read + write scopes)

`office-core` alone does NOT cover Contacts, Tracker, Forms, or Directory.
Each of those requires a separate app authorization.

Non-interactive URL extraction: `oauth_setup.py` is interactive (prompts for
token), but the URL is printed to stdout *before* the prompt. Extract with:
```bash
python3 <skill>/scripts/oauth_setup.py --account <alias> --app <app_id> 2>&1 | grep "oauth.yandex.ru"
```
Do NOT wrap in `timeout` — it causes the process to be blocked/killed before
output flushes. Plain execution + grep works because the URL prints before the
interactive token prompt blocks.

## Common Workflows

Mail:
- Check recent mail without persistence:
  `python3 <full-path-to-yandex-office>/mail/scripts/fetch_emails.py --account <alias> --dry-run --num <limit>`
- Preview matching mail body without persistence:
  `python3 <full-path-to-yandex-office>/mail/scripts/fetch_emails.py --account <alias> --dry-run --preview-body --sender <sender-or-pattern>`
- Fetch one known message:
  `python3 <full-path-to-yandex-office>/mail/scripts/fetch_emails.py --account <alias> --uid <uid>`
- Send an email:
  `python3 <full-path-to-yandex-office>/mail/scripts/send_email.py --account <alias> --to <addr> --subject <subj> --body <text>`
- Send with CC/BCC/HTML:
  `python3 <full-path-to-yandex-office>/mail/scripts/send_email.py --account <alias> --to <addr> --cc <addr> --bcc <addr> --subject <subj> --body <html> --content-type html --format json`
- Backfill from a UID floor without persisting state:
  use `--from-uid <uid>`. Exact single-message fetch uses `--uid <uid>`.
- Current Mail CLI uses `--account`; do not write legacy `--mailbox`.

Telemost transcripts:
- Check-only:
  `python3 <full-path-to-yandex-office>/mail/scripts/fetch_emails.py --account <alias> --filter telemost --dry-run`
- Actual bounded fetch:
  `python3 <full-path-to-yandex-office>/mail/scripts/fetch_emails.py --account <alias> --filter telemost --num <limit>`
- For "today", use `--since-date <YYYY-MM-DD>`.
- After actual fetch, process via `telemost/telemost.md`.

Calendar with Telemost:
- Resolve account.
- Check `apps` for `office-core` or Calendar plus Telemost coverage.
- Open `calendars/calendar.md`.

Disk, Tracker, Contacts, Directory, Forms:
- Choose default app for read/search.
- Choose broader/write app only when requested or approved.
- Open the relevant sub-skill doc and pass `--account <alias>`.

## Extension Reference Link

For low-level Yandex API method extension or audit, read
`references/yandex-office-extension.md`. Do not add raw `token` parameters,
raw-token CLIs, `auth_call(...)` wrappers, parallel auth registries, per-method
response handling, or service-specific HTTP subclasses.

## Migration, Versioning, License

Yandex Search moved to `https://github.com/bizyumov/yandex-search-skill`.
Yandex Cloud infrastructure guidance lives in the private standalone
`yandex-cloud` skill repository.

`yandex-office` uses dated skill versions in `YYYY.MM.DD` format. Keep
`VERSION`, `CHANGELOG.md`, and skill metadata aligned.

MIT
