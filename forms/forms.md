---
name: forms
description: Forms / Формы — download form responses and results from Yandex Forms via API. Supports JSON export, XLSX export, form discovery, and monthly response statistics.
license: MIT
compatibility: Python 3.10+, network access to api.forms.yandex.net
metadata:
  author: bizyumov
  version: "2026.04.10"
---

# Yandex Forms / Формы

API client for Yandex Forms to download form responses, export results, and discover forms. Works with forms in Yandex 360 for Business organizations.

## Quick Start

```bash
# Discover forms and get monthly response statistics
python3 scripts/discover_forms.py --account mary

# Get stats for specific form(s)
python3 scripts/get_form_stats.py --form-id FORM_ID --account mary

# Export form responses to XLSX
python3 scripts/export_responses.py --form-id FORM_ID --account mary

# Export to specific directory
python3 scripts/export_responses.py --form-id FORM_ID --account mary --output ./my-forms/

# Get single answer by ID
python3 scripts/get_answer.py --answer-id 2037950340 --account mary
```

## What It Does

1. **Discovers** forms by scanning workspace emails and maintaining a registry
2. **Queries** API for monthly response statistics per form
3. **Exports** form responses in XLSX or JSON format
4. **Saves** results to structured directory under `{data_dir}/forms/`
5. **Tracks** export operations and polls for completion (async operations)

## API Limitations

**Important:** The Yandex Forms API is **read-only for form management**. It does **NOT** support programmatic form creation.

| Operation | Supported | Notes |
|-----------|-----------|-------|
| Get form settings | ✅ Yes | Read form structure, questions, logic |
| Export responses | ✅ Yes | XLSX/JSON export via async operations |
| Get single answer | ✅ Yes | Fetch individual response data |
| Submit answers | ✅ Yes | Public form submission endpoint |
| **Create form** | ❌ **No** | **Not supported by API** |
| **Update form** | ❌ **No** | **Not supported by API** |
| **Delete form** | ❌ **No** | **Not supported by API** |

**What this means:** You cannot use this skill (or any API client) to:
- Create new forms programmatically
- Clone personal forms to business forms automatically
- Modify existing form structure or questions

To create forms, you must use the web UI: https://forms.yandex.ru/cloud/admin

## Form Discovery

Since the Yandex Forms API does not provide a "list all forms" endpoint, this skill includes a discovery mechanism:

### How Discovery Works

1. **Scans** email archives (incoming/, archive/) for form references
2. **Extracts** form IDs from URLs and content
3. **Queries** API to verify accessibility and get statistics
4. **Maintains** a registry at `{data_dir}/forms/registry.json`

### Discovery Output

```json
{
  "forms": {
    "6800cd9202848f10b272a9cc": {
      "title": "Event Registration Form",
      "api_accessible": true,
      "status": "published",
      "stats": {
        "total_responses": 150,
        "monthly": {
          "2025-01": 45,
          "2025-02": 67,
          "2025-03": 38
        }
      }
    }
  }
}
```

## Prerequisites

### Form Type: Business Forms Only

**Important:** The Yandex Forms API only works with **"Формы для бизнеса" (Business Forms)**. 

| Form Type | URL Pattern | API Access |
|-----------|-------------|------------|
| **Личные формы** (Personal) | `/u/FORM_ID` | ❌ Not supported |
| **Формы для бизнеса** (Business) | `/surveys/FORM_ID` | ✅ Supported |

If your form URL contains `/u/`, it's a personal form and cannot be accessed via API.

### Converting Personal Form to Business

To access a form via API, you need to either:
1. **Recreate the form** in the Business section: https://forms.yandex.ru/cloud/admin
2. **Transfer to organization** (if supported by your Yandex 360 setup)

### OAuth Token with Forms Scope

You need an OAuth token with `forms:read` scope (for reading responses) or `forms:write` (for full operations).

**Important:** You can only access forms that are visible to the authenticated user in the Yandex Forms UI. If you can't see a form when logged into forms.yandex.ru, the API will return 404.

Add to existing token file:
```json
{
  "email": "user@yandex.ru",
  "token.forms": "y0__..."
}
```

Or generate new token:
```bash
# From the agent workspace CWD, using the full path to the shared Yandex skill:
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py \
  --email user@yandex.ru \
  --account mary \
  --service forms
```

Recommended: use the default Forms app from root `config.json` (`oauth_apps.service_defaults.forms`, currently `forms-read`) so the default approval link can use the preconfigured app permissions without needing `--client-id` each time. Use `--app forms-full` when you need write access.

### Multiple Accounts

You can add multiple account tokens to access forms from different users:

```
{data_dir}/auth/
├── mary.token      # First account
├── admin.token      # Admin account with broader access
└── owner.token      # Form owner account
```

Then use `--account` to specify which token to use:
```bash
python3 scripts/get_form_stats.py --form-id FORM_ID --account admin
```

### OAuth App Registration

1. Go to https://oauth.yandex.ru/
2. Create new app → "Для доступа к API или отладки"
3. Add permission: "Просмотр настроек форм (forms:read)" or "Изменение настроек форм (forms:write)"
4. Get Client ID
5. Generate token with forms scope

## CLI Reference

### discover_forms.py

Discover forms and get monthly response statistics. Scans workspace emails for form references and queries API for accessible forms.

```bash
python3 scripts/discover_forms.py --account ACCOUNT [options]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--account` | Yes | Account name from config (e.g., `mary`) |
| `--output` | No | Output file for results (JSON) |
| `--no-scan` | No | Skip workspace scan, use existing registry only |
| `--json` | No | Output as JSON instead of formatted text |

**Example:**
```bash
# Discover forms and display summary
python3 scripts/discover_forms.py --account mary

# Save to JSON
python3 scripts/discover_forms.py --account mary --output ./forms-report.json

# Use existing registry without scanning
python3 scripts/discover_forms.py --account mary --no-scan
```

**Output:**
```
============================================================
Yandex Forms Discovery Results
Account: mary
============================================================

Total forms in registry: 3
API accessible: 2
Not accessible: 1

Accessible Forms with Response Totals:
------------------------------------------------------------

📋 Event Registration Form
   ID: 6800cd9202848f10b272a9cc
   Total responses: 150
   Monthly breakdown:
      2025-03: 38 responses
      2025-02: 67 responses
      2025-01: 45 responses
```

### get_form_stats.py

Get response statistics for specific form(s), including monthly breakdown. This is useful when you know the form IDs and want detailed response counts.

```bash
python3 scripts/get_form_stats.py --form-id FORM_ID [--form-id FORM_ID2 ...] --account ACCOUNT [options]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--form-id` | Yes | Form ID (can specify multiple) |
| `--account` | Yes | Account name from config (e.g., `mary`) |
| `--limit` | No | Max responses to fetch (default: 1000) |
| `--output` | No | Output file (JSON) |
| `--json` | No | Output as JSON instead of formatted text |

**Example:**
```bash
# Get stats for single form
python3 scripts/get_form_stats.py --form-id 6800cd9202848f10b272a9cc --account mary

# Get stats for multiple forms
python3 scripts/get_form_stats.py \
  --form-id FORM_ID_1 \
  --form-id FORM_ID_2 \
  --form-id FORM_ID_3 \
  --account mary

# Save to JSON
python3 scripts/get_form_stats.py \
  --form-id 6800cd9202848f10b272a9cc \
  --account mary \
  --output ./stats.json
```

**Output:**
```
======================================================================
Yandex Forms Response Statistics
======================================================================

📋 Event Registration Form
   ID: 6800cd9202848f10b272a9cc
   Status: published
   Total responses: 150

   Monthly breakdown:
   Month        Count                  First                   Last
   ----------------------------------------------------------------------
   2025-03         38   2025-03-01 09:00:00   2025-03-31 18:30:00
   2025-02         67   2025-02-01 10:15:00   2025-02-28 16:45:00
   2025-01         45   2025-01-05 08:30:00   2025-01-28 14:20:00
```

### export_responses.py

Export all responses from a form to XLSX file.

```bash
python3 scripts/export_responses.py --form-id FORM_ID --account ACCOUNT [options]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--form-id` | Yes | Form ID (e.g., `6800cd9202848f10b272a9cc`) |
| `--account` | Yes | Account name from config (e.g., `mary`) |
| `--output` | No | Output directory (default: `{data_dir}/forms/`) |
| `--format` | No | Export format: `xlsx` or `json` (default: `xlsx`) |
| `--wait` | No | Poll interval seconds (default: 5) |

**Example:**
```bash
python3 scripts/export_responses.py \
  --form-id 6800cd9202848f10b272a9cc \
  --account mary \
  --output ./downloads/ \
  --format xlsx
```

**Output:**
```
{data_dir}/forms/
└── 6800cd9202848f10b272a9cc/
    ├── responses_2026-03-03_080512.xlsx
    └── meta.json
```

### list_forms.py

List forms accessible to the account.

```bash
python3 scripts/list_forms.py --account mary [--limit 10]
```

### get_answer.py

Get a single answer by ID.

```bash
python3 scripts/get_answer.py --answer-id 2037950340 --account mary [--output ./answer.json]
```

## Output Structure

```
{data_dir}/forms/
├── registry.json                     # Forms registry with stats
├── {form_id}/
│   ├── responses_{timestamp}.xlsx  # Exported responses
│   ├── responses_{timestamp}.json  # JSON export (if requested)
│   └── meta.json                     # Form metadata
└── state.json                        # Export tracking state
```

### meta.json Fields

```json
{
  "form_id": "6800cd9202848f10b272a9cc",
  "account": "mary",
  "export_format": "xlsx",
  "exported_at": "2026-03-03T08:05:12Z",
  "operation_id": "0946779c-6a57-4070-b062-5d7ebdb65142",
  "filename": "responses_2026-03-03_080512.xlsx",
  "record_count": 42
}
```

## Use Cases

### 1. Monthly Survey Data Collection

Schedule weekly exports of survey responses for reporting:

```bash
# Cron: Every Monday at 9 AM
0 9 * * 1 python3 forms/scripts/export_responses.py --form-id SURVEY_ID --account mary --output ./reports/
```

### 2. Event Registration Processing

After an event, export all registrations:

```bash
python3 scripts/export_responses.py \
  --form-id EVENT_REG_FORM_ID \
  --account mary \
  --format xlsx \
  --output ./events/2026-03-conference/
```

### 3. Form Response Backup

Automated backup of critical form data:

```bash
#!/bin/bash
# backup_forms.sh
FORMS=("form1_id" "form2_id" "form3_id")
for FORM_ID in "${FORMS[@]}"; do
  python3 scripts/export_responses.py \
    --form-id "$FORM_ID" \
    --account mary \
    --output ./backups/$(date +%Y-%m)/
done
```

### 4. Integration with Data Pipeline

Export and process responses automatically:

```python
from scripts.export_responses import export_form_responses

# Export to temporary location
result = export_form_responses(
    form_id="6800cd9202848f10b272a9cc",
    account="mary",
    output_dir="./form_data",
    fmt="json"
)

# Process the JSON data
import json
with open(result['json_path']) as f:
    responses = json.load(f)
    # Your processing logic here
```

## API Endpoints Used

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/surveys/{id}/answers/export` | POST | Start async export operation |
| `/v1/operations/{id}` | GET | Check export operation status |
| `/v1/surveys/{id}/answers/export-results` | GET | Download exported file |
| `/v1/answers` | GET | Get single answer data |
| `/v1/surveys/{id}/answers` | GET | Paginated answer list |
| `/v1/users/me/` | GET | Verify authentication |

## Configuration

Uses shared root `config.json` plus workspace `yandex-data/config.agent.json`. Key fields:

- `forms.state_file` — Export operation tracking file
- `forms.default_format` — Default export format (xlsx/json)
- runtime data dir defaults to `./yandex-data` from the agent workspace CWD, or `--data-dir` when explicitly passed

Optional forms-specific config:
```json
{
  "forms": {
    "state_file": "forms_state.json",
    "default_format": "xlsx",
    "export": {
      "poll_interval_seconds": 5,
      "max_wait_seconds": 300
    }
  }
}
```

## Token Format

```json
{
  "email": "user@yandex.ru",
  "token.forms": "y0__..."
}
```

Stored at `{data_dir}/auth/{account}.token` with 600 permissions.

## Error Handling

Common errors and solutions:

| Error | Cause | Solution |
|-------|-------|----------|
| `401 Unauthorized` | Invalid/expired token | Refresh OAuth token |
| `403 Forbidden` | No access to form | Check form permissions in Yandex Forms UI |
| `404 Not Found` | Form doesn't exist / No access / **Personal form** | Verify it's a Business Form (`/surveys/ID` not `/u/ID`) |
| `202 Accepted` (stuck) | Export taking long | Increase `--wait` interval or check manually |

**Note on 404 errors:** The API returns 404 for:
- Forms that don't exist
- Forms you don't have access to
- **Personal forms** (`/u/...` URLs) — API only supports Business Forms (`/surveys/...`)

## Scenarios

### Scenario 1: Monthly Form Discovery and Reporting

Schedule monthly discovery to track all forms and their response statistics across the organization:

```bash
# Monthly discovery job
python3 scripts/discover_forms.py \
  --account mary \
  --output ./reports/forms-$(date +%Y-%m).json

# Export data for each discovered form
for form_id in $(jq -r '.forms | keys[]' ./reports/forms-$(date +%Y-%m).json); do
  python3 scripts/export_responses.py \
    --form-id "$form_id" \
    --account mary \
    --format xlsx \
    --output ./reports/$(date +%Y-%m)/
done
```

### Scenario 2: Research Data Collection

A research team uses Yandex Forms for survey data collection. Weekly automated exports ensure data is backed up and available for analysis in Excel-compatible format.

```bash
# Weekly export job
python3 scripts/export_responses.py \
  --form-id RESEARCH_SURVEY_ID \
  --account mary \
  --format xlsx \
  --output ./research/data/
```

### Scenario 3: Event Management

An event organizer collects registrations via Yandex Forms. After registration closes, they export all responses to process attendee lists.

```bash
# Post-event export
python3 scripts/export_responses.py \
  --form-id EVENT_REG_ID \
  --account mary \
  --format json

# Process with jq
cat responses.json | jq '.answers[] | select(.data[] | select(.id == "attending" and .value == true))'
```

### Scenario 4: Quality Assurance Forms

Support team uses forms for customer feedback. Daily exports feed into a dashboard pipeline.

```bash
# Daily morning export
python3 scripts/export_responses.py \
  --form-id FEEDBACK_FORM_ID \
  --account mary \
  --output ./dashboard/input/
```

## Files

- `scripts/discover_forms.py` — **Form discovery and monthly statistics** (scans workspace)
- `scripts/get_form_stats.py` — **Get response stats for specific form(s)** with monthly breakdown
- `scripts/export_responses.py` — Export form responses to XLSX/JSON
- `scripts/list_forms.py` — List accessible forms
- `scripts/get_answer.py` — Get single answer details
- `scripts/fetch.sh` — Cron-safe shell wrapper with PID lock

## Dependencies

```
requests>=2.28.0
```

Install: `pip install -r requirements.txt`

## References

- [Yandex Forms API Documentation](https://yandex.ru/support/forms/ru/api-ref/about)
- [API Access Setup](https://yandex.ru/support/forms/ru/api-ref/access)
- [API Examples](https://yandex.ru/support/forms/ru/api-ref/examples)
- [OAuth App Registration](https://yandex.ru/dev/id/doc/ru/register-api)
