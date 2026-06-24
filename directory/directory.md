# Yandex 360 Directory / Директория

## Overview

Yandex 360 Directory / Директория API integration for accessing organization users, departments, and calendar free/busy information. Works alongside Calendar and Contacts skills to enable "find common meeting time" workflows.

## API Discovery

### Base URL
```
https://api360.yandex.net/directory/v1
```

**⚠️ Host pitfall:** `cloud-api.yandex.net` is the Yandex **Disk** API host, not the Directory API host. Any `/directory/v1/...` request sent there returns `404 Not Found` (no such resource on the Disk host) — which looks like a permission or wrong-ID error but is a wrong-host error. Use `https://api360.yandex.net` only.

### Authentication
- Managed OAuth token linked to an app covering `directory:read_users`, `directory:read_departments`, `directory:read_groups`
- Use managed auth authorized through
  `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py`, normally with
  `--app directory-read`

### Required Scopes
```
directory:read_users         # Read employee data
directory:read_departments   # Read department structure
directory:read_groups        # Read groups
```

---

## Core Endpoints

### 1. List Organization Users

**Request:**
```
GET /org/{orgId}/users
```

**Query Parameters:**
- `page` — Page number (default: 1)
- `perPage` — Items per page (default: 10, max: 1000)
- `departmentId` — Filter by department (optional)
- `groupId` — Filter by group (optional)

**Managed CLI** (implemented — `directory/scripts/list.py`):
```bash
python3 <full-path-to-yandex-office>/directory/scripts/list.py \
  --account mary \
  --org-id 123456 \
  --per-page 1000
```

**Response Fields:**
- `users` — Array of user objects
- `page` — Current page number
- `pages` — Total pages
- `perPage` — Items per page
- `total` — Total users count

### 2. Get User by ID

**Request:**
```
GET /org/{orgId}/users/{userId}
```

### 3. Get Organization Info

**Request:**
```
GET /org
```

Returns organizations accessible through managed auth for the selected account alias.

---

## User Object Structure

```json
{
  "id": "123456",
  "nickname": "lebedevea",
  "departmentId": 23,
  "email": "user@example.com",
  "name": {
    "first": "Евгений",
    "last": "Лебедев",
    "middle": "Александрович"
  },
  "position": "Руководитель по операционной деятельности",
  "isAdmin": true,
  "isEnabled": true,
  "timezone": "Europe/Moscow"
}
```

---

## displayName (Public Name)

`displayName` is the user's **public name** — the name shown in the user's public profile. It is distinct from the Directory `name` block (`first`/`last`/`middle`). Set it via the same PATCH endpoint:

```
PATCH https://api360.yandex.net/directory/v1/org/{orgId}/users/{userId}
{"displayName": "Имя Фамилия"}
```

Via the skill CLI:

```bash
python3 <full-path-to-yandex-office>/directory/scripts/update_user.py \
  --account alice --org-id 123456 --user-id 1120000000000001 --display-name "Имя Фамилия"
```

Three non-obvious behaviors:

- **Set-only (cannot be cleared).** `{"displayName": null}` and `{"displayName": ""}` are silently ignored (`HTTP 200`, no change). Yandex auto-generates a neutral placeholder public name, so the field is never truly empty; you can only replace it with another non-empty value.
- **Moderated by Yandex ID.** Public names are reviewed against the Yandex ID public-data rules. Values containing **brand/company names, official or organizational titles, or trademarks** are auto-rejected and reverted to the placeholder shortly after being set. See [Публичные данные — Яндекс ID](https://yandex.ru/support/id/ru/data/public-data) and [Правила пользования сервисами Яндекса](https://yandex.ru/legal/rules/ru/). Functional/shared (non-person) accounts often have no descriptive name that passes moderation.
- **Returned only when set.** The `displayName` field is absent from a GET response until a value has been applied.

---

## Scenarios

### 1. Search User by Name

**Workflow:**
1. Get total user count via `perPage=1`
2. If total <= 1000: fetch all in one request
3. If total > 1000: paginate through pages
4. Search locally in returned data

**Implementation status:** unimplemented design contract. Do not run until
`directory/scripts/search.py` exists. Tracking issue:
`directory/ISSUE-directory-cache-and-identity.md`.

**Planned CLI Interface:**
```bash
python3 <full-path-to-yandex-office>/directory/scripts/search.py \
  --account mary \
  --query "Лебедев"
```

**Implementation:**
```python
def search_user(account, org_id, query):
    all_users = []
    page = 1
    
    while True:
        resp = get_users(account, org_id, page=page, perPage=1000)
        users = resp.get('users', [])
        all_users.extend(users)
        
        if len(users) < 1000:
            break
        page += 1
    
    # Fuzzy search locally
    matches = fuzzy_search(all_users, query)
    return matches
```

### 2. Find Common Free Time for Meeting

**Prerequisites:** managed Calendar auth for free/busy queries

**Workflow:**
1. Resolve organizer email → user ID (via directory)
2. Resolve attendee email → user ID (via directory)
3. Query free/busy for both users
4. Find intersection of free slots
5. Suggest best time

**Implementation status:** unimplemented design contract. Do not run until
`directory/scripts/find_slot.py` exists. Tracking issue:
`directory/ISSUE-directory-cache-and-identity.md`.

**Planned CLI Interface:**
```bash
python3 <full-path-to-yandex-office>/directory/scripts/find_slot.py \
  --account mary \
  --attendee "user@example.com" \
  --date 2026-03-04 \
  --duration 60
```

### 3. Cache Organization Users

**Workflow:**
1. Fetch all users (with pagination)
2. Save to local cache
3. Use cache for searches
4. Refresh cache periodically (daily)

**Cache Structure:**
```json
{
  "orgId": "123456",
  "lastUpdated": "2026-03-03T21:30:00Z",
  "total": 43,
  "users": [
    {"id": "...", "name": {...}, "email": "..."}
  ],
  "byEmail": {
    "user@example.com": "123456"
  },
  "byLastName": {
    "лебедев": ["123456"]
  }
}
```

---

## Directory Structure

```
directory/
├── directory.md              # This file
├── ISSUE-directory-cache-and-identity.md
└── scripts/
    ├── list.py               # DirectoryApi client + read CLI (orgs/users)
    ├── update_user.py        # Update user fields incl. displayName
    └── test_directory.py     # Unit tests (mocked HTTP)
```

---

## Integration Points

### Calendar Skill
```python
# Calendar create_event integration uses:
from directory.skill_api import resolve_user, find_common_slot

# Resolve "Лебедев" → email + ID
contact = resolve_user("mary", "Лебедев")

# Check free/busy
slot = find_common_slot("mary", ["user@example.com", contact.email])
```

### Contacts Skill
```python
# Sync directory users to CardDAV
from directory.skill_api import get_all_users

users = get_all_users("mary")
for u in users:
    contacts.add_if_not_exists(u)
```

---

## Error Handling

### Common Errors

**403 Forbidden**
- Cause: The selected account alias has no authorized app covering `directory:read_users`, or provider policy blocks access
- Fix: Refresh/import Directory-capable managed auth through `yandex-office` under user authorization

**404 Not Found**
- Cause: Directory user/principal not in this organization
- Fix: Check email or search across all orgs
- Cause (also): **wrong API host** — a `/directory/v1/...` request sent to `cloud-api.yandex.net` (the Disk API) returns `404`. Use `https://api360.yandex.net`. An insufficient role or OAuth scope instead returns **`403 Forbidden`** (`"No required scope"`), never `404`.

**Pagination Issues**
- Wrong: `pageSize=100` → returns 10 (default)
- Right: `perPage=100` → returns 100

---

## Configuration

Add shared defaults to root `config.skill.json` and directory-specific local settings to `yandex-data/config.agent.json`:
```json
{
  "directory": {
    "cache_ttl_hours": 24,
    "default_per_page": 1000,
    "search_fuzzy_threshold": 0.6
  }
}
```

---

## References

- Yandex 360 API Docs: https://yandex.ru/dev/api360/doc/
- UserService List: https://yandex.ru/dev/api360/doc/ru/ref/UserService/UserService_List

## Notes

- Default `perPage` is 10 (too small)
- Maximum `perPage` is 1000
- For 10,000 users → need 10 pages
- Always cache locally for search performance
- Telegram formatting: use bullets, not tables
