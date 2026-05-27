# OAuth Account Routing Pitfalls

Use this when changing `scripts/oauth_setup.py` or `common/oauth_token_import.py` around screen-code completion or managed-token import.

## Invariant

Managed token import must preserve this resolution order:

1. Verify the token and get the real Yandex email/client_id.
2. If a token file already has that verified email, write to that existing alias and warn if `--account` differs.
3. Else, if `--account <alias>` was supplied, write to that exact alias.
4. Else derive a new alias from the verified email.

The user-reported failure mode was step 3: no account existed for the verified email, but code still derived a new alias from that email instead of writing to the requested `--account`.

## What not to do

- Do not change `--account` into a global override that ignores an existing email-bound account.
- Do not remove the existing mismatch warning for the case where the verified email is already bound to another alias.
- Do not add a one-off helper function for JSON output if the file already uses local `json.dumps(...)` / `_print_account_info` / `_print_warnings` patterns.
- Do not answer bug reports by restating the user’s command/output. Inspect the branch, identify the broken assumption, and patch that branch.

## Tests to keep

Cover both cases:

- New verified email + `--account test` => writes `auth/test.token`; does not create derived alias file.
- Existing verified email in `auth/bdi.token` + `--account test` => writes `auth/bdi.token`; emits mismatch warning; does not create `auth/test.token`.

Screen-code complete should print a token-safe JSON work report: status, operation, token processed/saved flags, requested account, saved account, verified email, app_id/client_id, apps after import, and token path. Never print the token.
