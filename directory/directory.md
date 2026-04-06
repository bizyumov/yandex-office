# Yandex 360 Directory / Директория

## Overview

Yandex 360 Directory / Директория API integration for accessing organization users, departments, and calendar free/busy information. Works alongside Calendar and Contacts skills to enable "find common meeting time" workflows.

## API Discovery

### Base URL
```
https://api360.yandex.net/directory/v1
```

### Authentication
- OAuth 2.0 token with `directory:read_users`, `directory:read_departments`, `directory:read_groups` scopes
- Token field: `{account}.token` → `token.directory`

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

**Example:**
```bash
curl "https://api360.yandex.net/directory/v1/org/123456/users?page=1&perPage=1000" \
  -H "Authorization: OAuth $TOKEN"
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

Returns list of organizations accessible to the token.

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

## Scenarios

### 1. Search User by Name

**Workflow:**
1. Get total user count via `perPage=1`
2. If total <= 1000: fetch all in one request
3. If total > 1000: paginate through pages
4. Search locally in returned data

**CLI:**
```bash
python3 directory/scripts/search.py \
  --account mary \
  --query "Лебедев"
```

**Implementation:**
```python
def search_user(token, org_id, query):
    all_users = []
    page = 1
    
    while True:
        resp = get_users(token, org_id, page=page, perPage=1000)
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

**Prerequisites:** Calendar API access for free/busy queries

**Workflow:**
1. Resolve organizer email → user ID (via directory)
2. Resolve attendee email → user ID (via directory)
3. Query free/busy for both users
4. Find intersection of free slots
5. Suggest best time

**CLI:**
```bash
python3 directory/scripts/find_slot.py \
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
├── scripts/
│   ├── search.py            # Search users by name/email
│   ├── list.py              # List all users
│   ├── find_slot.py         # Find common free time
│   └── sync_cache.py        # Sync to local cache
├── lib/
│   ├── __init__.py
│   ├── client.py            # API client
│   ├── cache.py             # Cache management
│   └── search.py            # Fuzzy search logic
└── tests/
```

---

## Integration Points

### Calendar Skill
```python
# calendar/scripts/create_event.py uses:
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
- Cause: Token lacks `directory:read_users` scope
- Fix: Regenerate token with required scopes

**404 Not Found**
- Cause: User not in this organization
- Fix: Check email or search across all orgs

**Pagination Issues**
- Wrong: `pageSize=100` → returns 10 (default)
- Right: `perPage=100` → returns 100

---

## Configuration

Add shared defaults to root `config.json` and directory-specific overrides to `yandex-data/config.agent.json`:
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
