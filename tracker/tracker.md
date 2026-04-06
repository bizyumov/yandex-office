---
name: tracker
description: Tracker / Трекер — Yandex Tracker API client for task management. Create, search, update issues; manage comments, transitions, boards, and sprints. Integrates with mail, telemost, calendar, and directory services.
license: MIT
compatibility: Python 3.10+, network access to api.tracker.yandex.net
metadata:
  author: bizyumov
  version: "0.1"
---

# Yandex Tracker / Трекер

API client for Yandex Tracker to manage tasks, projects, and agile workflows. Works with organizations in Yandex 360 for Business and Yandex Cloud.

## Quick Start

```bash
# Search issues with query language
python3 scripts/search_issues.py --query "Queue: PROJ Status: open" --account mary

# Create a new issue
python3 scripts/create_issue.py --queue PROJ --summary "New task title" --account mary

# Get issue details
python3 scripts/get_issue.py --issue PROJ-123 --account mary

# Add comment to issue
python3 scripts/add_comment.py --issue PROJ-123 --text "Status update" --account mary

# List my open issues
python3 scripts/my_issues.py --account mary

# Get board columns and issues
python3 scripts/get_board.py --board 123 --account mary
```

## What It Does

1. **Searches** issues using powerful query language or filters
2. **Creates** issues with all metadata (assignee, priority, tags, due dates)
3. **Updates** issue status, assignee, priority, and custom fields
4. **Manages** comments with mentions and attachments
5. **Transitions** issues through workflow states
6. **Lists** boards, sprints, and their issues
7. **Integrates** with other Yandex services for workflow automation

## Prerequisites

### OAuth Token with Tracker Scope

You need an OAuth token with `tracker:read` (for reading) or `tracker:write` (for full operations) scope.

Add to existing token file:
```json
{
  "email": "user@yandex.ru",
  "token.tracker": "y0__..."
}
```

Or generate new token:
```bash
python3 <full-path-to-yandex-skills>/scripts/oauth_setup.py \
  --email user@yandex.ru \
  --account mary \
  --service tracker
```

Recommended: use the default Tracker app from root `config.json` (`oauth_apps.service_defaults.tracker`, currently `tracker-read`) for the default onboarding path. Use `--app tracker-full` for write access, and explicit `--client-id` and `--scope` only when you need a one-off override.

### Organization ID

Tracker API requires organization identifier:

- For **Yandex 360** organizations: use `X-Org-ID` header
- For **Yandex Cloud** organizations: use `X-Cloud-Org-ID` header

Store org ID in token file:
```json
{
  "email": "user@yandex.ru",
  "token.tracker": "y0__...",
  "org_id": "123456",
  "org_type": "360"  # or "cloud"
}
```

To find your org ID: https://tracker.yandex.ru/admin/orgs

## CLI Reference

### search_issues.py

Search issues using Yandex Tracker query language or filters.

```bash
python3 scripts/search_issues.py --account ACCOUNT [options]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--account` | Yes | Account name from config (e.g., `mary`) |
| `--query` | No* | Search query in Tracker query language |
| `--filter` | No* | JSON filter object (alternative to query) |
| `--queue` | No | Filter by queue key |
| `--assignee` | No | Filter by assignee login |
| `--status` | No | Filter by status |
| `--limit` | No | Max results (default: 50) |
| `--output` | No | Output file (JSON) |

*Either `--query` or `--filter` required unless using `--queue`

**Query Language Examples:**
```bash
# My open tasks
python3 scripts/search_issues.py --account mary --query "Assignee: me() Status: open"

# High priority bugs in specific queue
python3 scripts/search_issues.py --account mary --query 'Queue: PROJ Type: bug Priority: high'

# Overdue tasks
python3 scripts/search_issues.py --account mary --query "Deadline: < today() Status: !closed"

# Tasks created this week
python3 scripts/search_issues.py --account mary --query 'Created: >= "-7d"'
```

**Output:**
```
============================================================
Yandex Tracker Search Results
Account: mary
============================================================

Found 3 issues:

------------------------------------------------------------
📋 PROJ-124: Prepare quarterly report
   Status: 🟡 In Progress
   Assignee: Ivan Petrov
   Priority: High
   Updated: 2026-03-07 14:30
   Link: https://tracker.yandex.ru/PROJ-124
------------------------------------------------------------
📋 PROJ-123: Review documentation
   Status: 🔴 Open
   Assignee: Unassigned
   Priority: Normal
   Deadline: 2026-03-10
   Link: https://tracker.yandex.ru/PROJ-123
```

### create_issue.py

Create a new issue in specified queue.

```bash
python3 scripts/create_issue.py --queue QUEUE --summary SUMMARY --account ACCOUNT [options]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--queue` | Yes | Queue key (e.g., `PROJ`) |
| `--summary` | Yes | Issue title |
| `--account` | Yes | Account name |
| `--description` | No | Issue description (supports YFM markdown) |
| `--type` | No | Issue type (default: `task`) |
| `--priority` | No | Priority: `critical`, `high`, `normal`, `low` |
| `--assignee` | No | Assignee login or `me()` |
| `--followers` | No | Comma-separated list of followers |
| `--tags` | No | Comma-separated tags |
| `--due-date` | No | Due date (YYYY-MM-DD) |
| `--parent` | No | Parent issue key (for subtasks) |
| `--output` | No | Output file for created issue |

**Examples:**
```bash
# Simple task
python3 scripts/create_issue.py --queue PROJ --summary "Review PR #42" --account mary

# Task with all metadata
python3 scripts/create_issue.py \
  --queue PROJ \
  --summary "Critical bug in production" \
  --description "## Steps to reproduce\n1. Open app\n2. Click button" \
  --type bug \
  --priority critical \
  --assignee petrov \
  --tags "urgent,backend" \
  --due-date 2026-03-10 \
  --account mary
```

### get_issue.py

Get detailed information about a specific issue.

```bash
python3 scripts/get_issue.py --issue ISSUE_KEY --account ACCOUNT [options]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--issue` | Yes | Issue key (e.g., `PROJ-123`) |
| `--account` | Yes | Account name |
| `--with-comments` | No | Include comments in output |
| `--with-transitions` | No | Include available transitions |
| `--output` | No | Output file (JSON) |

### add_comment.py

Add a comment to an issue.

```bash
python3 scripts/add_comment.py --issue ISSUE --text TEXT --account ACCOUNT [options]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--issue` | Yes | Issue key |
| `--text` | Yes | Comment text (supports YFM) |
| `--account` | Yes | Account name |
| `--summon` | No | Comma-separated logins to mention |
| `--add-to-followers` | No | Add self to followers (default: true) |

**Example:**
```bash
python3 scripts/add_comment.py \
  --issue PROJ-123 \
  --text "@petrov @ivanov Please review the updated design" \
  --summon petrov,ivanov \
  --account mary
```

### update_issue.py

Update issue fields or status.

```bash
python3 scripts/update_issue.py --issue ISSUE --account ACCOUNT [options]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--issue` | Yes | Issue key |
| `--account` | Yes | Account name |
| `--summary` | No | New title |
| `--description` | No | New description |
| `--status` | No | New status (key or display name) |
| `--assignee` | No | New assignee (login or `me()` or `empty()`) |
| `--priority` | No | New priority |
| `--resolution` | No | Resolution when closing |
| `--add-tags` | No | Comma-separated tags to add |
| `--remove-tags` | No | Comma-separated tags to remove |
| `--due-date` | No | New due date (YYYY-MM-DD) |
| `--follow` | No | Add self to followers |
| `--unfollow` | No | Remove self from followers |

**Examples:**
```bash
# Change assignee
python3 scripts/update_issue.py --issue PROJ-123 --assignee petrov --account mary

# Close issue with resolution
python3 scripts/update_issue.py \
  --issue PROJ-123 \
  --status closed \
  --resolution "fixed" \
  --account mary

# Add tags
python3 scripts/update_issue.py --issue PROJ-123 --add-tags "frontend,urgent" --account mary

# Take issue to work
python3 scripts/update_issue.py \
  --issue PROJ-123 \
  --assignee me() \
  --status "in_progress" \
  --follow \
  --account mary
```

### my_issues.py

List issues assigned to current user.

```bash
python3 scripts/my_issues.py --account ACCOUNT [options]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--account` | Yes | Account name |
| `--status` | No | Filter by status (default: open) |
| `--queue` | No | Filter by queue |
| `--priority` | No | Filter by priority |
| `--limit` | No | Max results (default: 20) |
| `--overdue` | No | Show only overdue issues |

### get_board.py

Get board columns and issues (Agile board).

```bash
python3 scripts/get_board.py --board BOARD_ID --account ACCOUNT [options]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--board` | Yes | Board ID (number) |
| `--account` | Yes | Account name |
| `--output` | No | Output file (JSON) |

### get_queues.py

List available queues for the user.

```bash
python3 scripts/get_queues.py --account ACCOUNT [options]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--account` | Yes | Account name |
| `--output` | No | Output file (JSON) |

## Output Structure

```
{data_dir}/tracker/
├── issues/
│   └── {issue_key}.json       # Cached issue data
├── searches/
│   └── {timestamp}_{query}.json  # Search results
└── meta.json                     # Tracker metadata
```

## Integration Scenarios

### Scenario 1: Email → Task Creation

Automatically create tracker tasks from important emails:

```python
# When mail skill fetches email with specific tag:
from scripts.create_issue import create_issue

issue = create_issue(
    queue="SUPPORT",
    summary=f"[Email] {email_subject}",
    description=f"From: {sender}\n\n{email_body}",
    assignee="support-team",
    tags="from-email",
    account="mary"
)
```

### Scenario 2: Meeting → Action Items

After Telemost meeting processing, create tasks from action items:

```python
# Parse transcript.txt for action items:
# "@ivanov will prepare the report by Friday"

from scripts.create_issue import create_issue

issue = create_issue(
    queue="PROJ",
    summary="Prepare report (from meeting)",
    description=f"Action item from {meeting_date} meeting\n\nContext: {transcript_excerpt}",
    assignee="ivanov",
    due_date="2026-03-15",
    tags=f"meeting,{meeting_uid}",
    account="mary"
)
```

### Scenario 3: Task Due Date Reminders

Cron job to notify about upcoming deadlines:

```bash
# Daily check for tasks due tomorrow
python3 scripts/search_issues.py \
  --account mary \
  --query 'Deadline: "+1d" Status: !closed' \
  --output ./due_tomorrow.json

# Send notifications via Telegram
```

### Scenario 4: Form Response → Task

Process Yandex Forms submissions as tracker tasks:

```python
# When forms skill exports responses:
for response in form_responses:
    if response["urgent"]:
        create_issue(
            queue="REQUESTS",
            summary=response["title"],
            description=response["details"],
            priority="high",
            assignee="ops-team",
            account="mary"
        )
```

### Scenario 5: Calendar Event → Linked Task

Link calendar events with tracker tasks:

```python
# Before meeting, check for linked tasks
tasks = search_issues(
    query=f'Tag: "event-{event_id}"',
    account="mary"
)

# Add meeting notes as comment after
add_comment(
    issue=task_key,
    text=f"Meeting notes: {meeting_summary}",
    account="mary"
)
```

### Scenario 6: Directory Lookup for Assignment

Use Directory API to find right assignee:

```python
# Find team lead for department
from yandex_org import get_department_head

assignee = get_department_head("backend")

# Create task assigned to them
create_issue(
    queue="PROJ",
    summary="Technical review needed",
    assignee=assignee,
    account="mary"
)
```

## Token Format

```json
{
  "email": "user@yandex.ru",
  "token.tracker": "y0__...",
  "org_id": "123456",
  "org_type": "360"
}
```

Stored at `{data_dir}/auth/{account}.token` with 600 permissions.

## Error Handling

Common errors and solutions:

| Error | Cause | Solution |
|-------|-------|----------|
| `401 Unauthorized` | Invalid/expired token | Refresh OAuth token |
| `403 Forbidden` | No access to queue/issue | Check permissions in Tracker UI |
| `404 Not Found` | Issue/queue doesn't exist | Verify key exists |
| `409 Conflict` | Version conflict (concurrent edit) | Refetch and retry |
| `422 Validation Error` | Invalid field values | Check field types and values |

## Query Language Reference

Yandex Tracker uses powerful query language similar to JQL.

**Common Operators:**
- `Queue: PROJ` — issues in queue
- `Status: open` — by status
- `Assignee: me()` — my issues
- `Priority: high` — by priority
- `Created: >= "-7d"` — created in last 7 days
- `Deadline: < today()` — overdue
- `Tags: ~ "urgent"` — by tag
- `Summary: ~ "bug"` — text search in title
- `Description: ~ "error"` — text search in description

**Logical Operators:**
- `AND` / `OR` — combine conditions
- `!` / `not` — negation
- `()` — grouping

**Examples:**
```
Queue: PROJ AND Status: open AND Priority: high
Deadline: < today() AND Status: !closed
Assignee: empty() AND Created: >= "-30d"
```

## Files

- `scripts/search_issues.py` — Search issues with query/filter
- `scripts/create_issue.py` — Create new issues
- `scripts/get_issue.py` — Get issue details
- `scripts/update_issue.py` — Update issue fields/status
- `scripts/add_comment.py` — Add comments with mentions
- `scripts/my_issues.py` — List current user's issues
- `scripts/get_board.py` — Get Agile board data
- `scripts/get_queues.py` — List available queues
- `scripts/tracker_client.py` — Core API client class
- `scripts/fetch.sh` — Cron-safe wrapper with PID lock

## Dependencies

```
requests>=2.28.0
python-dateutil>=2.8.0
```

Install: `pip install -r requirements.txt`

## References

- [Yandex Tracker API Documentation](https://yandex.ru/support/tracker/ru/about-api)
- [Query Language Reference](https://yandex.ru/support/tracker/ru/user/query-filter)
- [Python Client on GitHub](https://github.com/yandex/yandex_tracker_client)
- [OAuth App Registration](https://oauth.yandex.ru/)

## API Endpoints Used

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v3/myself` | GET | Current user info |
| `/v3/issues/_search` | POST | Search issues |
| `/v3/issues` | POST | Create issue |
| `/v3/issues/{id}` | GET | Get issue |
| `/v3/issues/{id}` | PATCH | Update issue |
| `/v3/issues/{id}/comments` | POST | Add comment |
| `/v3/boards` | GET | List boards |
| `/v3/boards/{id}` | GET | Get board |
| `/v3/queues` | GET | List queues |
| `/v3/queues/{key}` | GET | Get queue info |

## Future Enhancements

- [ ] Bulk issue operations
- [ ] Sprint management
- [ ] Time tracking integration
- [ ] Webhook handling for issue updates
- [ ] Custom field management
- [ ] Workflow automation triggers
