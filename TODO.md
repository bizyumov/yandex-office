# Yandex Skills TODO

## Overview

This document contains all discovered issues and required changes for the yandex-office suite based on production testing. Items are prioritized by severity.

---

## 🔴 CRITICAL: disk - Telemost Recordings OAuth Issue

### Problem
Telemost meeting recordings (audio/video) with `yadi.sk` public share links **require OAuth authentication** to download via API. Without token, API returns 404 "DiskNotFoundError" even though links appear to be public.

### Current Behavior

| Request Type | With Token | Without Token |
|--------------|------------|---------------|
| `GET /v1/disk/public/resources/download` | ✅ Returns working download URL | ❌ 404 DiskNotFoundError |
| `HEAD` (any endpoint) | ❌ 405 Method Not Allowed | ❌ 302 redirect to captcha |

### Root Cause
- Telemost recordings are not truly public; they require owner's OAuth token
- Current `download.py` doesn't use OAuth token for "public" files

### Required Changes

1. **Update `scripts/download.py`**:
   - For `yadi.sk` links, always attempt OAuth authentication if token is available
   - Don't assume "public" means "no auth required"
   - Add `--force-auth` flag to explicitly use token even for public-looking URLs

2. **Update `disk/disk.md`** documentation:
   ```markdown
   ## Important: Telemost Recordings
   
   Telemost meeting recordings require OAuth authentication despite having 
   public share links (`yadi.sk/d/...`).
   
   ### API Behavior
   - HEAD requests: NOT supported (always returns 405)
   - GET without token: 404 "Resource not found" for Telemost files
   - GET with OAuth token: Returns working download URL
   
   ### Usage for Telemost
   Ensure YANDEX_DISK_TOKEN is set:
   ```bash
   export YANDEX_DISK_TOKEN="y0__..."
   python3 scripts/download.py "https://yadi.sk/d/..." --output ./
   ```
   ```

3. **Add test case**:
   - Test downloading a Telemost recording with and without token
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
`yandex-office` is a meta-skill containing multiple sub-skills (mail, disk, telemost, cloud). The structure is not immediately obvious, and users may look for `mail` as a separate top-level skill.

### Required Changes

1. **Update root `SKILL.md`** with clear structure diagram:
   ```markdown
   ## Structure
   
   This is a meta-skill containing multiple Yandex service integrations:
   
   ```
   yandex-office/
   ├── SKILL.md              (this file - overview)
   ├── config.json           (shared configuration)
   ├── mail/          (IMAP email fetching)
   │   └── mail.md
   ├── disk/          (file downloads)
   │   └── disk.md
   ├── telemost/      (meeting transcript processing)
   │   └── telemost.md
   └── cloud/         (cloud services)
       └── cloud.md
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
   ├── telemost/           └── disk.md
   │   └── SKILL.md           ├── telemost/
   └── cloud/
       └── SKILL.md           └── cloud/
                                  └── cloud.md
   ```
   
   This eliminates confusion with multiple `SKILL.md` files and makes navigation
   explicit: "For mail, see `mail/mail.md`".

---

## 🟢 LOW: General Improvements

### 1. Environment Variable Handling

**Issue**: Skills look for tokens in different places (env vars, `{account}.token` files).

**Fix**: Standardize token resolution order in all skills:
1. Environment variable (e.g., `YANDEX_DISK_TOKEN`)
2. `{data_dir}/auth/{account}.token` file
3. `{data_dir}/auth/default.token` fallback

### 2. Error Messages

**Issue**: 404 errors are generic and don't hint at OAuth requirement.

**Fix**: Add contextual error handling:
```python
if response.status == 404 and "yadi.sk" in public_url:
    logger.error("404 Not Found. Telemost recordings require OAuth token. "
                 "Set YANDEX_DISK_TOKEN or ensure token file exists.")
```

### 3. Logging Verbosity

**Issue**: It's hard to debug what's happening during API calls.

**Fix**: Add `--verbose` flag to all scripts that logs:
- API endpoints being called
- Auth method being used (token vs none)
- Response status codes

---

## Test Checklist

Before marking these tasks complete, verify:

- [ ] Can download Telemost audio with `YANDEX_DISK_TOKEN` set
- [ ] Get 404 (with helpful error message) without token
- [ ] HEAD request returns 405 (documented, not confusing)
- [ ] `fetch_emails.py --dry-run` works and shows pending emails (NOTE: `migrate_meeting_dirs.py` already has `--dry-run`)
- [ ] Root SKILL.md clearly explains meta-skill structure
- [ ] All sub-skills reference root config properly

---

## Related Files

- `/home/velizar/src/migrate-openclaw/skills/yandex-office/config.json` - Shared config
- `/home/velizar/src/migrate-openclaw/skills/yandex-office/disk/scripts/download.py` - Needs OAuth fix
- `/home/velizar/src/migrate-openclaw/skills/yandex-office/disk/disk.md` - Needs Telemost docs
- `/home/velizar/src/migrate-openclaw/skills/yandex-office/mail/scripts/fetch_emails.py` - Needs `--dry-run` (NOTE: `migrate_meeting_dirs.py` already has it)
- `/home/velizar/src/migrate-openclaw/skills/yandex-office/SKILL.md` - Needs structure diagram

---

## Notes from Testing

**Test Case: Telemost Audio Download**
```bash
# This should work
export YANDEX_DISK_TOKEN="y0__..."
python3 disk/scripts/download.py "https://yadi.sk/d/kvnJPr7okDIY4g" --output ./downloads/

# This should fail with helpful error
unset YANDEX_DISK_TOKEN
python3 disk/scripts/download.py "https://yadi.sk/d/kvnJPr7okDIY4g" --output ./downloads/
# Expected: Error message explaining OAuth requirement
```

**Discovered API Quirks:**
- Yandex Disk API doesn't support HEAD requests (always 405)
- Telemost public links aren't truly public (need owner's OAuth)
- 404 can mean "not found" OR "exists but you need auth"

---

*Last updated: 2026-02-27*
*Testing performed with a placeholder example account*
