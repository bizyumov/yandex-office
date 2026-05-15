# Yandex Skills TODO

## Overview

This document contains all discovered issues and required changes for the yandex-office suite based on production testing. Items are prioritized by severity.

---

## 🔴 CRITICAL: disk - Telemost Recordings OAuth Issue

### Problem
Telemost meeting recordings (audio/video) with `yadi.sk` public share links may require managed OAuth authentication for the selected account alias to download via API. Without managed auth, API returns 404 "DiskNotFoundError" even though links appear to be public.

### Current Behavior

| Request Type | With managed auth | Without managed auth |
|--------------|------------|---------------|
| `GET /v1/disk/public/resources/download` | ✅ Returns working download URL | ❌ 404 DiskNotFoundError |
| `HEAD` (any endpoint) | ❌ 405 Method Not Allowed | ❌ 302 redirect to captcha |

### Root Cause
- Telemost recordings are not necessarily public; organization-restricted links
  can look public while remaining inaccessible through the public-link API

### Required Changes

1. **Update `disk/scripts/download.py`**:
   - Keep public-link API methods tokenless
   - Route non-public Disk operations through decorator-declared auth lookup
   - Require `--account` unless exactly one token-backed account exists

2. **Update `disk/disk.md`** documentation:
   ```markdown
   ## Important: Telemost Recordings
   
   Telemost meeting recordings require OAuth authentication despite having 
   public share links (`yadi.sk/d/...`).
   
   ### API Behavior
   - HEAD requests: NOT supported (always returns 405)
   - GET without managed auth: 404 "Resource not found" for Telemost files
   - GET with managed auth for the selected account alias: Returns working download URL
   
   ### Usage for Telemost
   Ensure `yandex-office` has a managed Disk token for the selected account alias:
   ```bash
   python3 <full-path-to-yandex-office>/disk/scripts/download.py "https://yadi.sk/d/..." --account <account> --output ./
   ```
   ```

3. **Add test case**:
   - Test downloading a Telemost recording with and without managed auth
   - Document expected 404 vs 200 behavior

---

## 🟡 MEDIUM: mail - Documentation Clarity

### Problem
The relationship between `fetch_emails.py`, `incoming/` directory, and downstream processing is not clearly documented. Users may browse `archive/` or `meetings/` instead of fetching new emails.

### Required Changes

1. **Update `mail/mail.md`** with explicit data flow:
   ```markdown
   ## Data Flow
   
   1. **Fetch**: `fetch_emails.py` downloads from IMAP → `incoming/`
   2. **Process**: Downstream skills (telemost) process raw `incoming/` emails into rich `meetings/`
   3. **Archive**: Processed emails move to `archive/`
   
   ⚠️ **Never check `archive/` or `meetings/` for "new" data** — 
   always run `fetch_emails.py` first.
   ```

2. **Add `--dry-run` flag** to `fetch_emails.py`:
   - Show what would be downloaded without actually downloading
   - List pending emails with UID, subject, sender, timestamp
   - Useful for checking "what's new" without modifying state
   
   Note: `migrate_meeting_dirs.py` already has `--dry-run` for directory migration,
   but `fetch_emails.py` lacks this feature.

---

## 🟡 MEDIUM: Meta-Skill Structure Documentation

### Problem
`yandex-office` is a meta-skill containing multiple sub-skills (mail, disk, telemost, calendar, contacts, directory, forms, tracker). The structure is not immediately obvious, and users may look for `mail` as a separate top-level skill.

### Required Changes

1. **Update root `SKILL.md`** with clear structure diagram:
   ```markdown
   ## Structure
   
   This is a meta-skill containing multiple Yandex service integrations:
   
   ```
   yandex-office/
   ├── SKILL.md              (this file - overview)
	   ├── config.skill.json     (shared configuration)
   ├── mail/          (IMAP email fetching)
   │   └── mail.md
   ├── disk/          (file downloads)
   │   └── disk.md
   ├── telemost/      (meeting transcript processing)
   │   └── telemost.md
   ├── forms/         (Forms API)
   │   └── forms.md
   └── tracker/       (Tracker API)
       └── tracker.md
   ```
   
   Each subfolder is an independent skill with its own documentation.
   ```

2. **Restructure skill layout** (ACTION REQUIRED - breaking change):
   
   Rename sub-skill folders and their docs for clarity:
   ```
   BEFORE:                    AFTER:
   yandex-office/      yandex-office/
   ├── mail/           ├── SKILL.md (root index)
   │   └── SKILL.md           ├── mail/
   ├── disk/               └── mail.md
   │   └── SKILL.md           ├── disk/
   └── telemost/
       └── SKILL.md           └── telemost/
                                  └── telemost.md
   ```
   
   This eliminates confusion with multiple `SKILL.md` files and makes navigation
   explicit: "For mail, see `mail/mail.md`".

---

## 🟢 LOW: General Improvements

### 1. Environment Variable Handling

**Issue**: Older code looked for tokens in multiple direct credential sources.

**Fix**: Standardize token resolution in all skills through decorator-declared
managed auth lookup, with account inference only when there is exactly one
account alias.

### 2. Error Messages

**Issue**: 404 errors are generic and don't hint at OAuth requirement.

**Fix**: Add contextual error handling:
```python
if response.status == 404 and "yadi.sk" in public_url:
    logger.error("404 Not Found. The public-link API cannot access this resource.")
```

### 3. Logging Verbosity

**Issue**: It's hard to debug what's happening during API calls.

**Fix**: Add `--verbose` flag to all scripts that logs:
- API endpoints being called
   - Auth method being used (managed auth vs public)
- Response status codes

---

## Test Checklist

Before marking these tasks complete, verify:

- [ ] Stored-account Disk operations use decorator-declared managed auth lookup
- [ ] Public-link API gets 404 for organization-restricted links when tokenless
- [ ] HEAD request returns 405 (documented, not confusing)
- [ ] `fetch_emails.py --dry-run` works and shows pending emails (NOTE: `migrate_meeting_dirs.py` already has `--dry-run`)
- [ ] Root SKILL.md clearly explains meta-skill structure
- [ ] All sub-skills reference root config properly

---

## Related Files

- `<full-path-to-yandex-office>/config.skill.json` - Shared config
- `<full-path-to-yandex-office>/disk/scripts/download.py` - Needs managed auth fix
- `<full-path-to-yandex-office>/disk/disk.md` - Needs Telemost docs
- `<full-path-to-yandex-office>/mail/scripts/fetch_emails.py` - Needs `--dry-run` (NOTE: `migrate_meeting_dirs.py` already has it)
- `<full-path-to-yandex-office>/SKILL.md` - Needs structure diagram

---

## Notes from Testing

**Test Case: Telemost Audio Download**
```bash
# Public-link API path; organization-restricted links can return 404
python3 <full-path-to-yandex-office>/disk/scripts/download.py "https://yadi.sk/d/kvnJPr7okDIY4g" --output ./downloads/
```

**Discovered API Quirks:**
- Yandex Disk API doesn't support HEAD requests (always 405)
- Telemost public links aren't truly public (may need managed auth for an account that can access the asset)
- 404 can mean "not found" OR "exists but you need auth"

---

*Last updated: 2026-02-27*
*Testing performed with a placeholder example account*
