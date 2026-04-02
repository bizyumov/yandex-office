# Yandex Skills Onboarding (Operator Playbook)

This guide documents the **actual onboarding flow** for `mail` / `disk` in this repository, including edge cases, ambiguity points, and recommended UX copy.

---

## Scope

Covers:
- OAuth onboarding for Mail + Disk
- Shared config/data directory setup
- First fetch validation
- How to present choices to users without confusion

Does **not** cover:
- Yandex Search API onboarding. Search now lives in the standalone `yandex-search-skill` repository.
- Yandex Cloud infra deployment

---

## Preflight Checklist

Before asking the user for anything, verify:

1. `config.json` exists and is readable.
2. Agent config exists at `{cwd}/yandex-data/config.agent.json`.
3. `data_dir` points to an intended location.
4. Required dirs exist (or can be created):
   - `{data_dir}/auth`
   - `{data_dir}/incoming`
   - `{data_dir}/meetings`
5. Mailbox is confirmed (e.g. `user@example.com`).
6. Sender filter is confirmed (default often `keeper@telemost.yandex.ru`).

---

## OAuth Scopes (Critical)

Use these scopes:

- **Mail:** `mail:imap_ro` (read-only preferred)
- **Disk:** `cloud_api:disk.read`

### Important nuance
Mail and Disk may use **different OAuth apps** and therefore **different Client IDs**.

Do not assume one Client ID works for both services.

---

## Token Storage Contract

Path:
- `{data_dir}/auth/{account}.token`

Format:

```json
{
  "email": "user@yandex.ru",
  "token.mail": "y0_...",
  "token.disk": "y0_..."
}
```

Permissions:
- `600`

---

## Recommended Onboarding Flow

### Step 1 — Collect minimum inputs
Ask for:
- Mailbox email
- Account alias (e.g. `bdi`)
- Sender filter (or keep default)
- Data directory preference
- Optional explicit Client IDs only if no preconfigured app map exists yet

### Step 2 — Normalize config and directories
- Keep shared defaults in root `config.json`.
- Put mailbox-specific settings into `{cwd}/yandex-data/config.agent.json`.
- Keep the preconfigured OAuth app catalog and default service bindings in root `config.json` under `oauth_apps.catalog` and `oauth_apps.service_defaults`.
- Create `auth`, `incoming`, `meetings`.

### Step 3 — Issue mail token
Run:

```bash
python scripts/oauth_setup.py \
  --email user@yandex.ru \
  --account bdi \
  --service mail
```

Recommended behavior:

- resolve the default Mail app from `oauth_apps.service_defaults.mail`
- resolve its `client_id` and baked-in scopes from `oauth_apps.catalog.<app_id>`
- generate a ready-made approval link with no `scope=` parameter
- rely on the app's baked-in permissions

User returns access token; save to `token.mail`.

### Step 4 — Issue disk token
Run:

```bash
python scripts/oauth_setup.py \
  --email user@yandex.ru \
  --account bdi \
  --service disk
```

For advanced/operator flows that need an explicit override:

```bash
python scripts/oauth_setup.py \
  --client-id DISK_CLIENT_ID \
  --scope cloud_api:disk.write \
  --scope cloud_api:disk.app_folder \
  --email user@yandex.ru \
  --account bdi \
  --service disk
```

If an app's permission set changes later, existing tokens must be reissued.

To use a non-default preconfigured app variant, pass `--app <app_id>` (for example `--app disk-full`).

### Step 5 — Validate with fetch
Run:

```bash
python mail/scripts/fetch_emails.py
```

Success indicators:
- IMAP connection established
- New emails processed
- Output appears in `{data_dir}/incoming`
- UID state persisted

---

## Where Existing Documentation Was Ambiguous

1. **Scope wording for Mail**
   - Ambiguity: docs previously implied/used `mail:imap_full`.
   - Fix: explicitly recommend `mail:imap_ro` for fetch-only workflows.

2. **Client ID reuse assumption**
   - Ambiguity: examples looked like one Client ID for both services.
   - Fix: explicitly state Mail and Disk may require different OAuth apps/Client IDs.

3. **Disk scope naming inconsistency**
   - Ambiguity: `disk:read` vs `cloud_api:disk.read`.
   - Fix: standardize on `cloud_api:disk.read` in scripts and docs.

4. **Data directory expectations**
   - Ambiguity: relative paths can point outside expected workspace.
   - Fix: recommend explicit absolute `data_dir` in operator onboarding.

5. **Operator prompts**
   - Ambiguity: no standard phrasing for user-facing choices.
   - Fix: use option-based prompts (templates below).

---

## How to Present Options to Users in Telegram (Inline Buttons)

Use Telegram inline buttons for scope choice instead of free-text templates.

### Mail scope chooser (recommended UX)

Present two buttons:
- `Request read-only mailbox access (recommended)`
- `Request full mailbox access`

Use `message.send` with inline buttons, e.g.:

```json
{
  "action": "send",
  "channel": "telegram",
  "target": "<chat_id>",
  "message": "Choose mailbox access level:",
  "buttons": [[
    {"text": "Read-only (mail:imap_ro)", "callback_data": "mail_scope:ro"},
    {"text": "Full access (mail:imap_full)", "callback_data": "mail_scope:full"}
  ]]
}
```

When callback is received:
- `mail_scope:ro`  -> scope = `mail:imap_ro`
- `mail_scope:full` -> scope = `mail:imap_full`

Then generate OAuth URL dynamically for the advanced explicit-scope path:

```text
https://oauth.yandex.ru/authorize?response_type=token&client_id={MAIL_CLIENT_ID}&scope={chosen_scope}
```

### Disk scope chooser (read vs read-write)

After mail token is stored, present two Disk options:

```json
{
  "action": "send",
  "channel": "telegram",
  "target": "<chat_id>",
  "message": "Choose Disk access level:",
  "buttons": [[
    {"text": "Read-only (cloud_api:disk.read)", "callback_data": "disk_scope:read"},
    {"text": "Read-write (cloud_api:disk.write)", "callback_data": "disk_scope:write"}
  ]]
}
```

Callback mapping:
- `disk_scope:read`  -> `cloud_api:disk.read`
- `disk_scope:write` -> `cloud_api:disk.write`

Then generate OAuth URL dynamically for the advanced explicit-scope path:

```text
https://oauth.yandex.ru/authorize?response_type=token&client_id={DISK_CLIENT_ID}&scope={chosen_disk_scope}
```

> Scope names verified from Yandex Disk API docs ("Доступ к API"): `cloud_api:disk.read`, `cloud_api:disk.write`.

### Notes

- Default recommendation in button labels should always be read-only.
- Keep callback payload short and deterministic (`mail_scope:ro`, `mail_scope:full`, etc.).
- After each callback, send the exact URL and ask user to paste **only** `access_token`.
- Do not include tokens in button payloads or logs.

---

## Operator Safety / Quality Rules

- Never log tokens in persistent docs/commits.
- Prefer read-only scopes unless write access is explicitly needed.
- Confirm scope from generated URL before asking user to authorize.
- After onboarding, run one real fetch test and report counts/results.
- If docs and script disagree, trust script behavior, then patch docs immediately.

---

## Suggested Post-Onboarding Report Format

```text
Onboarding complete ✅
- data_dir: ...
- mailbox: ...
- token.mail: present (readonly)
- token.disk: present (read)
- fetch test: success
- processed emails: N
- output dir: ...
```

---

## Quick Troubleshooting

- `AUTHENTICATE failed`: wrong scope, wrong token, wrong mailbox email.
- Empty fetch result: sender filter too strict or UID state already advanced.
- Token file missing fields: rerun oauth_setup with missing `--service`.
- Unexpected data path: confirm the process CWD and check `{cwd}/yandex-data/config.agent.json`.

---

## Maintainer Note

If onboarding was tested in a real chat session and exposed confusion, update this file first, then update `README.md`, root `SKILL.md`, and per-skill docs (`mail/mail.md`, `disk/disk.md`, etc.) to keep guidance aligned.
