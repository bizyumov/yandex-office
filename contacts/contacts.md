# Yandex Contacts / Контакты

## Overview

A CardDAV-based Contacts / Контакты skill for managing Yandex Contacts (Address Book), integrated with the Yandex skill ecosystem. Provides read/write access to contacts, fuzzy name search, and seamless integration with Calendar and Mail skills.

**Single Source of Truth:** Yandex CardDAV server is the primary source. Local cache is maintained for performance and offline access, but all writes go through to Yandex.

---

## API Discovery

### Endpoint
- **CardDAV URL**: `https://carddav.yandex.ru`
- **Protocol**: CardDAV (RFC 6352)
- **Authentication**: OAuth 2.0 token with `addressbook:all` scope

### Authentication
```json
{
  "email": "user@yandex.ru",
  "token.contacts": "y0_..."
}
```

Token stored per-account at: `{data_dir}/auth/{account}.token`

### Account Structure
- Each user has a principal: `/principals/users/{email}/`
- Addressbook home: `/addressbook/{email}/`
- Default addressbooks:
  - **Personal** — `/addressbook/{email}/1/` (user-created contacts)
  - **Shared** — `/addressbook/{email}/2/` (organization/shared contacts)
- Contact files: `{uuid}.vcf` (vCard 3.0 format)

---

## Scenarios

### 1. Search Contacts by Name

**User Request Examples:**
- "Find Ivan in my contacts"
- "What's the email for Ivanov?"
- "Show me all Transneft contacts"
- "Кто такой Иванов в моих контактах?"

**Requirements:**
- Fuzzy search across:
  - Full name (FN field)
  - Structured name components (N: Last;First;Middle)
  - Email addresses
  - Organization/Company
  - Phone numbers
- Support partial matches ("Вас" → "Иван")
- Support transliteration ("Ivan" → "Иван")
- Return ranked results with match confidence
- Handle Russian and English queries

**Output Format:**
```json
{
  "query": "Ivan",
  "account": "ctiis",
  "total_results": 3,
  "results": [
    {
      "uid": "uuid-here",
      "match_confidence": 0.95,
      "matched_field": "FN",
      "full_name": "Иванов Иван Иванович",
      "first_name": "Иван",
      "last_name": "Иванов",
      "middle_name": "Сергеевич",
      "emails": ["contact@example.com"],
      "phones": ["+7..."],
      "organization": "Транснефть",
      "source": "Personal"  // or "Shared"
    }
  ]
}
```

**CLI Interface:**
```bash
python3 contacts/scripts/search.py --account ctiis --query "Иван"
python3 contacts/scripts/search.py --account ctiis --query "Ivanov" --json
python3 contacts/scripts/search.py --account ctiis --domain "transneft.ru"
```

### 2. Add New Contact

**User Request Examples:**
- "Add Ivan Ivanov to contacts"
- "Save contact: Иванов Иван, contact@example.com"
- "Add contact from email" (extract from email headers)

**Requirements:**
- Required fields: at least one of (name, email, phone)
- Optional fields:
  - Full name (auto-parse from structured name if not provided)
  - Structured name: First, Last, Middle
  - Email(s) with type (work, home, other)
  - Phone(s) with type (work, home, mobile)
  - Organization, Job Title
  - Notes
- Auto-generate UID (UUID v4)
- Check for duplicates before adding (warn if similar contact exists)
- Support batch import from JSON/CSV

**Duplicate Detection:**
- Match by exact email
- Match by similar name + organization
- Prompt user for confirmation on potential duplicates

**CLI Interface:**
```bash
python3 contacts/scripts/add.py \
  --account ctiis \
  --first-name "Иван" \
  --last-name "Иванов" \
  --middle-name "Сергеевич" \
  --email "contact@example.com" \
  --org "Транснефть"

# Batch import
python3 contacts/scripts/add.py --account ctiis --from-json contacts.json
```

### 3. Update Existing Contact

**User Request Examples:**
- "Update Ivan's phone number"
- "Add work email to Ivanov"
- "Change organization for all Transneft contacts"

**Requirements:**
- Search for contact first (fuzzy match)
- Handle ambiguous matches (list candidates)
- Support partial updates (only change specified fields)
- Preserve existing data not being modified
- Update vCard and sync to server

**CLI Interface:**
```bash
python3 contacts/scripts/update.py \
  --account ctiis \
  --search "Иванов" \
  --phone "+79161234567" \
  --phone-type "mobile"

# Update by UID
python3 contacts/scripts/update.py \
  --account ctiis \
  --uid "uuid-here" \
  --org "Новая компания"
```

### 4. Delete Contact

**User Request Examples:**
- "Delete Ivan from contacts"
- "Remove all contacts from NLMK"

**Requirements:**
- Search first, show confirmation
- Safety prompt for bulk deletes
- Require --force for non-interactive deletion
- Soft delete option (move to archive before permanent delete)

**CLI Interface:**
```bash
python3 contacts/scripts/delete.py --account ctiis --search "Иванов"
python3 contacts/scripts/delete.py --account ctiis --uid "uuid" --force
```

### 5. Sync Contacts from Email History

**User Request Examples:**
- "Import all contacts from my emails"
- "Find contacts from Transneft domain and add them"
- "Sync contacts with full names only"

**Requirements:**
- Scan IMAP for email addresses with display names
- Parse Russian full names (Фамилия Имя Отчество)
- Filter by domain or organization
- Skip existing contacts (by email)
- Batch add with progress reporting
- Generate report of added/skipped/failed

**Heuristics for Name Parsing:**
- 3-word capitalized Russian text → Last First Middle
- Email prefix matching known pattern → derive name
- Common email formats: firstname.lastname@domain

**CLI Interface:**
```bash
python3 contacts/scripts/sync_from_email.py \
  --account ctiis \
  --domain "transneft.ru" \
  --require-full-name \
  --dry-run

# Full sync
python3 contacts/scripts/sync_from_email.py --account ctiis --all
```

### 6. List All Contacts

**User Request Examples:**
- "Show me all my contacts"
- "List contacts from Personal addressbook"
- "Export my contacts to JSON"

**Requirements:**
- Support filtering by source (Personal/Shared)
- Sort by name, organization, or email
- Export to JSON/CSV/vCard
- Paginated output for large contact lists

**CLI Interface:**
```bash
python3 contacts/scripts/list.py --account ctiis
python3 contacts/scripts/list.py --account ctiis --source Personal --json
python3 contacts/scripts/list.py --account ctiis --export contacts_backup.json
```

---

## Integration Points

### Calendar Skill Integration

**Contract:**
```python
# contacts/skill_api.py exposes:
def resolve_contact(account: str, query: str) -> Contact:
    """Search contacts by name/phrase, return best match or None."""
    
def get_contact_email(account: str, query: str) -> str:
    """Return primary email for contact, or query if not found."""
    
def suggest_attendees(account: str, partial_name: str, limit: int = 5) -> List[Contact]:
    """Return list of matching contacts for autocomplete."""
```

**Usage in Calendar:**
```bash
python3 calendar/scripts/create_event.py \
  --account ctiis \
  --contact "Иванов" \
  --start "2026-03-04T11:00:00" \
  --duration 60
```

### Mail Skill Integration

**Contract:**
```python
def add_contact_from_email(account: str, email_headers: dict) -> Contact:
    """Extract contact from email From/Reply-To and add to addressbook."""
    
def get_contact_by_email(account: str, email: str) -> Optional[Contact]:
    """Lookup contact by email address."""
```

---

## Technical Design

### Directory Structure
```
contacts/
├── contacts.md              # This file
├── scripts/
│   ├── search.py
│   ├── add.py
│   ├── update.py
│   ├── delete.py
│   ├── list.py
│   └── sync_from_email.py
├── lib/
│   ├── __init__.py
│   ├── client.py            # CardDAV client wrapper
│   ├── vcard.py             # vCard parsing/generation
│   ├── search.py            # Fuzzy search logic
│   ├── cache.py             # Local cache management
│   └── sync.py              # Email sync logic
└── tests/
```

### Dependencies
```
caldav>=3.0.0
vobject>=0.9.6
fuzzywuzzy>=0.18.0
python-Levenshtein>=0.21.0  # Speeds up fuzzy matching
```

### Configuration Extension
Add shared defaults to root `config.json` and contact-specific overrides to `yandex-data/config.agent.json`:
```json
{
  "contacts": {
    "default_addressbook": "Personal",
    "sync_on_startup": false,
    "cache_ttl_seconds": 300,
    "fuzzy_match_threshold": 0.6
  }
}
```

### State Files
```
{data_dir}/
├── auth/{account}.token     # Existing OAuth tokens
└── contacts/
    ├── cache.json           # Local contact cache
    ├── cache_meta.json      # Cache timestamps, ETags
    └── sync_state.json      # Email sync progress
```

### Cache Strategy
- **Read:** Check cache first, validate ETag with server (conditional GET)
- **Write:** Always write through to server, update cache on success
- **Background sync:** Optional periodic sync for large addressbooks
- **Invalidation:** ETag-based, manual refresh available

---

## Error Handling

### Common Error Cases
1. **Token expired** → Prompt for re-auth via existing OAuth flow
2. **Contact not found** → Suggest similar names, offer to create
3. **Duplicate detected** → Show existing contact, ask for confirmation
4. **CardDAV server error** → Retry with exponential backoff, fallback to cache
5. **Invalid vCard data** → Log error, skip contact, continue

### Error Format
```json
{
  "error": "duplicate_detected",
  "message": "Contact with email 'contact@example.com' already exists",
  "existing_contact": {
    "uid": "...",
    "full_name": "Иванов Иван Иванович"
  }
}
```

---

## Security Considerations

1. **Token storage**: Reuse existing `{data_dir}/auth/{account}.token` pattern
2. **No token logging**: Never log OAuth tokens
3. **Contact privacy**: Respect Yandex ACLs (Personal vs Shared addressbooks)
4. **Cache encryption**: Consider encrypting local cache at rest
5. **Export safety**: Warn when exporting contacts to unencrypted files

---

## Future Enhancements

1. **Yandex 360 Directory integration**: Query organization-wide contacts
2. **Contact groups/categories**: Support vCard CATEGORIES
3. **Contact photos**: Support PHOTO field (base64 encoded)
4. **Social profiles**: Support X-SOCIALPROFILE for LinkedIn, Telegram
5. **Conflict resolution**: UI for manual merge when sync conflicts occur
6. **Import/export**: Google Contacts, Outlook CSV, vCard bulk import

---

## References

- CardDAV RFC: https://datatracker.ietf.org/doc/html/rfc6352
- vCard RFC: https://datatracker.ietf.org/doc/html/rfc6350
- Yandex OAuth: https://yandex.ru/dev/id/doc/dg/oauth/reference/concepts.html
- CardDAV Python library: https://github.com/python-caldav/caldav
- vObject library: https://github.com/eventable/vobject
