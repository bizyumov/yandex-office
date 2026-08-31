---
name: yandex-office
description: Shared Yandex skill pack for Mail, Disk, Telemost, Calendar, Contacts, Directory, Forms, and Tracker. Yandex Search and Yandex Cloud live in separate standalone skill repos.
homepage: https://github.com/bizyumov/yandex-office
license: MIT
compatibility: Python 3.10+, per-skill dependencies, network access for Yandex APIs
metadata:
  author: bizyumov
  version: "2026.08.31"
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

- (1-16) Frontmatter (metadata version 2026.08.31)
- (17-25) Opening Model
- (27-39) Document Map
- (41-47) Reference Map
- (49-75) Account-First Workflow
- (77-108) Account And OAuth Helper
- (110-135) OAuth App Selector
- (137-160) Token Handling
- (162-195) Common Workflows
- (197-202) Extension Reference Link
- (204-213) Migration, Versioning, License

## Reference Map

- Auth model: `references/yandex-office-auth-principles.md`
- OAuth screen-code / PKCE flow: `references/oauth-screen-code-flow.md`
- Config and data shape: `references/config-data-and-tests.md`
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
- Start screen-code OAuth:
  `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --account <alias> --app <app_id> --code-flow start`
- Complete screen-code OAuth:
  `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --account <alias> --code-flow complete --code <confirmation-code>`

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

Examples: `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --account <alias> --app office-core --code-flow start`
then `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --account <alias> --code-flow complete --code <confirmation-code>`

To ensure an account covers a workflow, run `--account <alias>` and read `apps`.
For Calendar plus Telemost, acceptable coverage includes `office-core`, or both
`calendar-user` and `telemost-default`. Runtime API responses remain final truth.

## Token Handling

The user authorizes OAuth tokens. `yandex-office` verifies and stores them.
Never put an access token in visible command arguments, final text, logs, or
artifacts. Warnings print to stderr; stdout is the resolved alias or a structured
JSON report, depending on the command.

Prefer the Yandex screen-code flow for new OAuth setup. It creates a PKCE
authorization URL, stores managed tokens and pending verifier state under
`~/secrets/yandex-office`, migrates missing secrets once from legacy
`{data_dir}/auth`, and never prints the returned bearer token.

```bash
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --account <alias> --app <app_id> --code-flow start
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --account <alias> --code-flow complete --code <confirmation-code>
```

Completion prints token-safe JSON with `requested_account`, `saved_account`,
`email`, `app_id`, `client_id`, `apps`, and `token_path`. For several pending
links, run one complete command per code; the CLI tries pending entries in issue
order and removes only the matched entry. Account routing is unified for all
managed imports: existing verified-email account wins, else explicit
`--account`, else derive an alias from verified email. Details live in
`references/oauth-screen-code-flow.md`.

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
