---
name: yandex-office
description: Shared Yandex skill pack for Mail, Disk, Telemost, Calendar, Contacts, Directory, Forms, and Tracker. Yandex Search and Yandex Cloud live in separate standalone skill repos.
homepage: https://github.com/bizyumov/yandex-office
license: MIT
compatibility: Python 3.10+, per-skill dependencies, network access for Yandex APIs
metadata:
  author: bizyumov
  version: "2026.05.16"
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

- (1-16) Frontmatter
- (17-25) Opening Model
- (27-39) Document Map
- (41-46) Reference Map
- (48-71) Account-First Workflow
- (73-104) Account And OAuth Helper
- (106-131) OAuth App Selector
- (133-150) Token Handling
- (152-181) Common Workflows
- (183-188) Managed Auth Link
- (190-199) Migration, Versioning, License

## Reference Map

- Auth model: `references/yandex-office-auth-principles.md`
- SMTP send implementation: `references/smtp-xoauth2-send.md`
- Config and data shape: `references/config-data-and-tests.md`
- Service overview: `references/yandex-service-reference.md`
- Low-level auth extension: `references/managed-auth-extension.md`

## Account-First Workflow

Run first:
`python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --accounts list`

If aliases print, choose only an exact listed alias. If no alias is suitable,
pause the business task and set up or import the account through `yandex-office`
under user authorization. If nothing prints, no account alias is configured in
this CWD yet; choose the minimum setup path from the user's request.

Then choose the sub-skill:
- Mail: `mail/mail.md`
- Calendar: `calendar/calendar.md`
- Telemost: `telemost/telemost.md`
- Disk: `disk/disk.md`
- Contacts: `contacts/contacts.md`
- Directory: `directory/directory.md`
- Forms: `forms/forms.md`
- Tracker: `tracker/tracker.md`

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

- Mail read/fetch: default `mail-readonly`; write-capable `mail-readwrite`.
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
artifacts. In non-interactive tool execution, use `--from-env`.
Warnings print to stderr; stdout is the resolved alias as one line.

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

## Full Authorization Workflow

To authorize an account across ALL yandex-office sub-skills with maximum
permissions, generate OAuth URLs for this set of apps:

1. `office-core` — Mail (read), Disk (full), Calendar, Telemost
2. `mail-readwrite` — Mail (send + delete via IMAP full)
3. `contacts-default` — Contacts (read + modify)
4. `tracker-full` — Tracker (read + write)
5. `forms-full` — Forms (read + write)
6. `directory-full` — Directory (all read + write scopes)

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

Mail (MUST run from workspace CWD, e.g. /opt/hermes/workspaces/mithril — NOT from skill dir):
- Discover messages from a sender:
  `python3 <skill>/mail/scripts/fetch_emails.py --account <alias> --sender "<pattern>" --dry-run --num 10`
- Fetch exactly one message by UID (no state change):
  `python3 <skill>/mail/scripts/fetch_emails.py --account <alias> --uid <uid>`
- Read fetched message: check `{data_dir}/incoming/<filter>/<date>_<alias>_uid<N>/email_body.txt` and `meta.json`
- Send an email:
  `python3 <skill>/mail/scripts/send_email.py --account <alias> --to <addr> --subject <subj> --body <text>`
- Send with CC/BCC/HTML/priority:
  `python3 <skill>/mail/scripts/send_email.py --account <alias> --to <addr> --cc <addr> --bcc <addr> --subject <subj> --body <html> --content-type html --format json`
- Current Mail CLI uses `--account`; do not write legacy `--mailbox`.
- Email headers: X-Priority/Importance work. Disposition-Notification-To does NOT trigger read receipts in practice.
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
- Open `calendar/calendar.md`.

Disk, Tracker, Contacts, Directory, Forms:
- Choose default app for read/search.
- Choose broader/write app only when requested or approved.
- Open the relevant sub-skill doc and pass `--account <alias>`.

## Pitfalls

- **NEVER use raw `imaplib` or `smtplib` for Yandex Mail operations.** Always use `fetch_emails.py` and `send_email.py` from this skill. Boris stopped me mid-session multiple times for writing raw `imaplib.IMAP4_SSL` / `smtplib.SMTP_SSL` calls instead of using the skill tools. The skill tools handle OAuth2 token dispatch, account resolution, state persistence, and structured output — raw stdlib calls bypass all of that. This is the single most important rule.
- **Read the skill docs FIRST, then act.** Boris repeatedly had to tell me to stop and read `mail/mail.md` before writing ad-hoc code. The workflow is: (1) read the sub-skill doc, (2) run the documented commands, (3) read the output from the structured directories. Do not improvise.
- **Do NOT use himalaya or any standalone email CLI.** Boris explicitly rejected himalaya ("Забудь как страшный сон свои Гималайи"). All mail operations — fetch and send — go through this skill's `mail/scripts/` directory.
- **SMTP auth uses XOAUTH2, not app passwords.** The `send_email.py` script authenticates via `@yandex_api_method("mail.smtp.send")` with the same OAuth2 token dispatch as IMAP. App passwords work for ad-hoc `smtplib` calls but bypass managed auth — do not use them in production.
- **Testing decorated methods.** `@yandex_api_method` wraps the original function. In unit tests, call `instance._method.__wrapped__(instance, ctx)` to bypass the decorator dispatch and test the SMTP/IMAP logic directly with a real `YandexApiContext` (not a MagicMock — the decorator reads `account`, `data_dir`, `config`, `session` attributes).
- **The `mail-readwrite` app does NOT include `mail:smtp` scope.** Currently `mail-readwrite` has only `mail:imap_full`. The `send_email.py` works with `one_of=["mail:imap_full", "mail:imap_ro"]` because Yandex SMTP accepts the same tokens as IMAP. If Yandex tightens scope enforcement, a new app entry with `mail:smtp` scope may be needed.
- **Email headers for importance and read receipt.** Use `X-Priority: 1`, `Importance: high`, `Disposition-Notification-To: <sender>` per RFC 3798 / RFC 4356. These are set on the `MIMEMultipart` message object before sending. Do NOT guess headers — check the RFCs.
- **Fetch a specific message for header analysis.** Use `--uid <N>` to fetch one message. The body and attachments land in `yandex-data/incoming/<filter>/`. Read `email_body.txt` and `meta.json` from there — do not parse raw IMAP yourself.

## Managed Auth Link

For low-level Yandex API method extension or audit, read
`references/managed-auth-extension.md`. Do not add raw `token` parameters,
raw-token CLIs, `auth_call(...)` wrappers, parallel auth registries, per-method
response handling, or service-specific HTTP subclasses.

## Migration, Versioning, License

Yandex Search moved to `https://github.com/bizyumov/yandex-search-skill`.
Yandex Cloud infrastructure guidance lives in the private standalone
`yandex-cloud` skill repository.

`yandex-office` uses dated skill versions in `YYYY.MM.DD` format. Keep
`VERSION`, `CHANGELOG.md`, and skill metadata aligned.

MIT
