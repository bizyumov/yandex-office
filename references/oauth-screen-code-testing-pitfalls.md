# OAuth screen-code testing pitfalls

Use this note when actively testing `scripts/oauth_setup.py --code-flow` behavior with a human sending short Yandex confirmation codes.

## Preserve the test state

- Do not manually edit or clear `{data_dir}/auth/oauth-code-flow.json` during a test unless the user explicitly asks for reset. The pending registry is the test artifact.
- If pending history is suspected to be stale or polluted, inspect and report it first; ask before destructive cleanup.
- Delete temporary accounts only after the user confirms testing is complete and any requested smoke checks have passed.

## Completion command discipline

- Follow the user's exact scope for account targeting:
  - If they say `in test` / `в test`, pass `--account test`.
  - If they say `without account` / `без указания аккаунта`, omit `--account` entirely.
- For multiple codes, process them in the user-supplied order and show the full JSON result for each completion.
- Do not infer that Yandex `invalid_grant: Code has expired` proves a human-entered code is expired when multiple pending flows exist. It can be the result of trying the code against the wrong pending verifier/app before the matching flow.

## What to report

For each code completion, report the full stdout JSON from the skill, including:

- `status`
- `operation`
- `requested_account`
- `saved_account`
- `email`
- `app_id`
- `client_id`
- `apps`
- `token_path`

Also report exit status and stderr if non-zero. Avoid paraphrasing away fields during debugging.

## Verification before cleanup

A successful `token_saved: true` proves managed import worked, not that every product API works. Before deleting a temporary account used for testing, run or offer smoke checks appropriate to the apps authorized, for example:

- Mail read/write for `mail-readwrite`
- SMTP send capability for `mail-smtp` when safe and explicitly scoped
- Disk/Calendar/Telemost coverage for `office-core`
- Directory/Forms/Tracker calls for their respective apps

If the user asks to delete immediately, delete; otherwise verify first when the goal is auth mechanism testing.
