# OAuth screen-code authorization flow

Use this reference when replacing token-paste onboarding for Yandex OAuth apps in `yandex-office`.

## Confirmed behavior

A live test against the existing `mail-readonly` app showed that Yandex accepts authorization-code exchange with PKCE and no `client_secret`:

1. Generate a random `code_verifier` and `code_challenge = base64url(sha256(code_verifier))`.
2. Send the user to:
   `https://oauth.yandex.ru/authorize?response_type=code&client_id=<client_id>&redirect_uri=https%3A%2F%2Foauth.yandex.ru%2Fverification_code&code_challenge=<challenge>&code_challenge_method=S256&state=<state>&force_confirm=yes`
3. User authorizes and copies the short confirmation code shown by Yandex.
4. POST to `https://oauth.yandex.ru/token` with form-urlencoded body:
   - `grant_type=authorization_code`
   - `code=<confirmation_code>`
   - `client_id=<client_id>`
   - `redirect_uri=https://oauth.yandex.ru/verification_code`
   - `code_verifier=<verifier>`
5. Yandex returns `access_token`, `expires_in`, and `refresh_token`.
6. Import the returned `access_token` through the existing managed import path (`import_managed_oauth_token`) without printing it.

A negative `/token` probe with an invalid code returned `bad_verification_code`, not `client_secret` errors; a valid live code exchanged successfully and verified through `login.yandex.ru/info` with the expected `client_id`.

## CLI design preference

For Telegram/Hermes use, prefer a direct second-phase CLI parameter for the short-lived confirmation code, e.g.:

```bash
python3 <skill>/scripts/oauth_setup.py --app mail-readonly --code-flow start
python3 <skill>/scripts/oauth_setup.py --code-flow complete --code <confirmation-code>
```

Do not require importing the confirmation code through an environment variable. It is short-lived and single-use; unlike an OAuth bearer token, direct CLI input is acceptable and less cumbersome. Continue to keep actual `access_token` and `refresh_token` out of visible args, logs, final text, and artifacts.

## Implementation notes

- Existing apps must allow `https://oauth.yandex.ru/verification_code` as a Redirect URI.
- Store all pending authorizations in one local registry file: `{data_dir}/auth/oauth-code-flow.json`. The registry contains an ordered `pending` list; list order is the link issue order and is the exchange attempt order. Do not expose or require a user-facing flow id.
- Each registry entry stores `state`, `code_verifier`, `client_id`, `app_id`, account/email hints, `created_at`, and `expires_at`.
- Exclude generation-time ties in code: assign each new `created_at` as a strictly increasing timestamp relative to the last registry entry, even when several links are generated in the same second.
- Yandex confirmation codes live for 10 minutes. Set `expires_at = created_at + 600` and print both the lifetime and expiry timestamp in `--code-flow start` output so the agent knows when the human-provided code will expire.
- Batch authorization UX: if several links were issued, the user should only paste the short codes. Do not ask them to label codes with app names, flow IDs, or link numbers. Run completion for each code in the order the user supplied it; each completion should try the registry `pending` entries in link issue order and remove only the matched entry after successful import.
- Test-session UX: when the human says this is a test, accept codes in whatever order they send them. Do not force a clean reset, regenerate links, or demand exact link order unless the human asks for that. If debugging a failed code, narrate the exact state checks and the exact completion command/result.
- Completion pitfall: one stale pending entry can return Yandex `invalid_grant` / `Code has expired` before the CLI reaches the matching fresh entry. Treat `invalid_grant`, `Code has expired`, `bad_verification_code`, and equivalent invalid-code responses as non-matches for that pending entry; continue through all pending entries and only fail after all candidates have been tried.
- Alias routing: when `--account <alias>` is supplied to completion or managed import, write the token to that exact alias. Do not derive another alias from the verified Yandex email; store the verified email inside the requested alias's token file.
- Completion report: successful `--code-flow complete` must print a token-safe JSON report to stdout with at least status, operation, token processed/saved flags, requested account, saved account, verified email, app id/client id, apps present after import, and token path. Do not print only the alias.
- Debugging posture: if the user sends an exact command, full output, and interpretation, treat it as a bug report. Do not answer with a Captain Obvious restatement; inspect the code path, identify the exact broken assumption or branch, then patch, test, commit, and report the concrete diff/evidence.
- Keep `response_type=token` as a legacy fallback until the code flow is fully rolled out.
- Future improvement: persist `refresh_token` and expiry metadata, then refresh expired access tokens automatically. Minimal MVP may import only `access_token` into the current managed-token model.

## Operational pitfalls

Before editing the `yandex-office` repo, create/switch to a feature branch. Do not begin implementation on `main`. If uncommitted edits are already present on `main`, `git switch -c <branch>` carries them to the new branch without committing or losing them.

When testing batch screen-code completion, preserve the pending registry unless the user explicitly asks to reset it. Do not delete or rewrite `{data_dir}/auth/oauth-code-flow.json` during a test run just to recover from errors; the registry order and history are part of the behavior under test.

A Yandex `/token` response like `invalid_grant` / `Code has expired` during completion is not by itself proof that the human's screen code has actually expired. In a multi-link batch, the CLI may be trying the code against a pending entry with the wrong `client_id`/PKCE verifier. The correct behavior is to continue through pending entries for mismatch-like errors and only report failure after all candidates have been tried. For proof, inspect the current registry order and, if needed, add temporary debug logging of `index`, `app_id`, and `client_id` before token exchange; never log `code_verifier`, access tokens, or refresh tokens.

During alias-routing tests, `--account <alias>` is an explicit write target, not a hint. If the verified Yandex email would derive another local alias, the requested alias must still receive the new token. Verify this by checking the JSON report's `saved_account`, `apps`, and `token_path`, then checking the requested alias with `oauth_setup.py --account <alias>`.
