# Yandex Skills Onboarding (Operator Playbook)

This guide documents the **actual onboarding flow** for `yandex-mail` / `yandex-disk` in this repository, including edge cases, ambiguity points, and recommended UX copy.

---

## Scope

Covers:
- OAuth onboarding for Mail + Disk
- Shared config/data directory setup
- First fetch validation
- How to present choices to users without confusion

Does **not** cover:
- Yandex Search API onboarding
- Yandex Cloud infra deployment

---

## Preflight Checklist

Before asking the user for anything, verify:

1. `config.json` exists and is readable.
2. `data_dir` points to an intended location (prefer explicit absolute path for production).
3. Required dirs exist (or can be created):
   - `{data_dir}/auth`
   - `{data_dir}/incoming`
   - `{data_dir}/meetings`
4. Mailbox is confirmed (e.g. `bdi@boevayaslava.ru`).
5. Sender filter is confirmed (default often `keeper@telemost.yandex.ru`).

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
- Mail Client ID
- Disk Client ID (allow same value if user knows it supports both scopes)
- Mailbox email
- Account alias (e.g. `bdi`)
- Sender filter (or keep default)
- Data directory preference

### Step 2 — Normalize config and directories
- Set `data_dir` to explicit path.
- Create `auth`, `incoming`, `meetings`.

### Step 3 — Issue mail token
Run:

```bash
python yandex-mail/scripts/oauth_setup.py \
  --client-id MAIL_CLIENT_ID \
  --email user@yandex.ru \
  --account bdi \
  --service mail
```

User returns access token; save to `token.mail`.

### Step 4 — Issue disk token
Run:

```bash
python yandex-mail/scripts/oauth_setup.py \
  --client-id DISK_CLIENT_ID \
  --email user@yandex.ru \
  --account bdi \
  --service disk
```

User returns access token; save to `token.disk`.

### Step 5 — Validate with fetch
Run:

```bash
python yandex-mail/scripts/fetch_emails.py --config /path/to/config.json
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

Then generate OAuth URL dynamically:

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

Then generate OAuth URL dynamically:

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
- Unexpected data path: resolve `data_dir` relative to `config.json` and switch to absolute path.

---

## Maintainer Note

If onboarding was tested in a real chat session and exposed confusion, update this file first, then update `README.md` + skill `SKILL.md` files to keep guidance aligned.
