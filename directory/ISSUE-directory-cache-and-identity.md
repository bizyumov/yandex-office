# [directory] Add org discovery, cached identity graph, and Telegram-to-Yandex resolution

## Summary

Expand the `directory` sub-skill from a read-only requirements stub into a real service layer for Yandex 360 organization data.

The skill must:

- discover `org_id` for admin-capable tokens via API
- cache organization users, departments, groups, and domain mappings
- monitor changes and refresh the cache
- resolve Yandex users by email, alias, and organization domain
- build and cache an identity graph:
  - Telegram user ID
  - email address
  - organization domain
  - Yandex user ID

This is required to support OpenClaw service workflows such as:

- “add me to the access list for this Yandex Disk shared file”

## Motivation

Current Disk sharing now works for:

- organization-only links (`employees`)
- user-specific access (`user_ids`)
- group-specific access (`group_ids`)
- department-specific access (`department_ids`)

But operational use still lacks a service skill that can answer:

- what is the `org_id` for this organization?
- what Yandex user ID corresponds to this email?
- what group/department IDs are relevant?
- what organization domain does this person belong to?
- how do we map a Telegram user in a group chat to an organization user identity?

Without this, group-based bot flows remain manual.

## Proposed Scope

### 1. Organization Discovery

Add API support to:

- `GET /directory/v1/org`

Requirements:

- use `token.directory` or legacy `token.org`
- require `directory:read_organization`
- if token is admin-capable, fetch accessible organizations and cache:
  - `org_id`
  - organization name
- if not authorized, fail explicitly instead of guessing

### 2. Cached Directory Data

Add sync/cache support for:

- users
- groups
- departments

Data sources:

- `GET /directory/v1/org/{orgId}/users`
- `GET /directory/v1/org/{orgId}/groups`
- `GET /directory/v1/org/{orgId}/departments`

Cache requirements:

- store raw normalized snapshots under `{data_dir}/directory/`
- support periodic refresh
- preserve last successful sync timestamp
- expose fast lookup indexes:
  - by email
  - by alias/nickname
  - by Yandex user ID
  - by Telegram ID
  - by organization domain

### 3. Org ID and Domain Association

Build and cache the association:

- `org_id -> organization metadata`
- `organization domain -> org_id`

Practical rule:

- derive domain associations from directory users' email addresses
- example:
  - `<org_id> -> example.com`

This avoids making every caller rediscover the same relationship.

### 4. Identity Resolution

Add identity resolution helpers:

- resolve Yandex user by exact email
- resolve Yandex user by alias/nickname
- resolve organization by email domain
- resolve Telegram user ID to Yandex identity

Identity graph shape:

```json
{
  "telegram_id": "123456",
  "email": "user@example.com",
  "domain": "example.com",
  "org_id": "123456",
  "yandex_user_id": "123456"
}
```

### 5. Telegram Binding Support

Add explicit support for OpenClaw group scenarios:

- user speaks in a Telegram group
- bot sees Telegram sender ID
- bot resolves sender identity:
  - Telegram ID -> email -> org domain -> Yandex user ID
- bot can then add that Yandex user to a Disk access list

This requires:

- a cache-backed mapping store
- a way to record or confirm Telegram-to-email linkage
- deterministic lookup behavior once linked

## Proposed Deliverables

### Python API

- `discover_orgs(account)`
- `sync_users(account, org_id)`
- `sync_groups(account, org_id)`
- `sync_departments(account, org_id)`
- `build_indexes(account, org_id)`
- `resolve_user_by_email(account, email)`
- `resolve_user_by_alias(account, alias)`
- `resolve_org_by_domain(domain)`
- `bind_telegram_identity(telegram_id, email)`
- `resolve_telegram_identity(telegram_id)`

### CLI

- `directory/scripts/orgs.py`
- `directory/scripts/sync_cache.py`
- `directory/scripts/resolve_user.py`
- `directory/scripts/bind_telegram.py`
- `directory/scripts/resolve_telegram.py`

### Cache Files

Under `{data_dir}/directory/`:

- `orgs.json`
- `users.json`
- `groups.json`
- `departments.json`
- `identity_links.json`
- `indexes.json`

## Auth Requirements

Minimum:

- `directory:read_users`
- `directory:read_departments`
- `directory:read_groups`

For org discovery:

- `directory:read_organization`

Important:

- org discovery is reliable only for tokens that actually have access to that information, which in practice means an admin path

## Test Case

### Telegram group access request

Scenario:

1. A user writes in a Telegram group:
   - “Добавь меня в доступ к этому файлу”
2. Bot identifies Telegram sender ID.
3. Bot resolves sender:
   - Telegram ID -> email alias -> organization domain -> Yandex user ID
4. Bot calls Disk sharing update:
   - append that Yandex user ID to `user_ids`
5. Bot confirms access was granted.

Acceptance criteria:

- resolution does not require manual Yandex user ID lookup at request time
- cached identities are reused across requests
- cache refresh updates users/groups/departments without losing Telegram bindings

## Notes

- This issue updates the skill name from legacy `org` terminology to canonical `directory`.
- Legacy token alias handling (`token.org -> token.directory`) should remain supported.
- Domain-to-org association should be cached centrally in `directory`, not reimplemented in `disk`.
