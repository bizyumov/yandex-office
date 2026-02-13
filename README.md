# yandex-skills

A collection of [agentskills.io](https://agentskills.io/specification)-compliant skills for working with Yandex platform services.

## Skills

| Skill | Description |
|-------|-------------|
| [yandex-mail](yandex-mail/) | Fetch emails via IMAP XOAUTH2, classify Telemost emails, extract meeting UIDs |
| [yandex-telemost](yandex-telemost/) | Process Telemost meetings — merge transcript + recording, UTC diarization |
| [yandex-disk](yandex-disk/) | Download public files from Yandex Disk (yadi.sk links) |
| [yandex-search](yandex-search/) | Web search via Yandex Cloud Search API v2 |
| [yandex-cloud](yandex-cloud/) | Deploy serverless functions to Yandex Cloud |

## Installation

### Full clone

```bash
git clone https://github.com/bizyumov/yandex-skills.git
```

### Single skill (sparse checkout)

```bash
git clone --filter=blob:none --sparse https://github.com/bizyumov/yandex-skills.git
cd yandex-skills
git sparse-checkout set yandex-mail

# Add more skills later
git sparse-checkout add yandex-telemost yandex-disk
```

## Typical Workflow

```
[Yandex Mail] → incoming/ → [Yandex Telemost] → documents/meetings/
                                    ↓
                             [Yandex Disk] (download recordings)
```

1. **yandex-mail** fetches Telemost emails on a cron schedule, writes to `incoming/`
2. **yandex-telemost** scans `incoming/`, groups by meeting UID, merges transcript + recording data
3. **yandex-disk** (optional) downloads video/audio from yadi.sk links

Each skill is self-contained and can be used independently.

## Yandex Platform Setup

### OAuth App Registration

| Step | URL |
|------|-----|
| Register API app | https://yandex.ru/dev/id/doc/ru/register-api |
| Create new API key | https://oauth.yandex.ru/client/new/api |
| View existing tokens | https://oauth.yandex.ru/ |

### Service-Specific Documentation

| Service | Documentation |
|---------|---------------|
| Yandex Disk API | https://yandex.ru/dev/disk-api/doc/ru/concepts/quickstart |
| Yandex Disk playground | https://yandex.ru/dev/disk/poligon/ |
| Yandex Mail IMAP | https://yandex.ru/support/mail/mail-clients/others.html |
| Yandex Cloud Search API | https://yandex.cloud/ru/docs/search-api/ |
| Yandex Cloud CLI | https://cloud.yandex.com/docs/cli/quickstart |

### OAuth Tokens

Each skill uses a **separate** OAuth token with minimal scopes:

| Skill | Token file | Required scopes |
|-------|-----------|----------------|
| yandex-mail | `data/auth/mail.token` | `mail:imap_full` |
| yandex-disk | `data/auth/disk.token` | `disk:read` |
| yandex-search | N/A (API key) | Yandex Cloud service account |
| yandex-cloud | N/A (yc CLI) | `yc init` |

Generate tokens with:
```bash
python yandex-mail/scripts/oauth_setup.py --service mail --client-id YOUR_ID --email user@yandex.ru
python yandex-mail/scripts/oauth_setup.py --service disk --client-id YOUR_ID --email user@yandex.ru
```

## Directory Structure

```
yandex-skills/
├── README.md
├── LICENSE
├── .gitignore
├── yandex-mail/
│   ├── SKILL.md
│   ├── scripts/
│   │   ├── fetch_emails.py
│   │   ├── oauth_setup.py
│   │   └── fetch.sh
│   ├── references/
│   └── config.example.json
├── yandex-telemost/
│   ├── SKILL.md
│   ├── scripts/
│   │   ├── process_meeting.py
│   │   └── process_transcript.py
│   └── references/
├── yandex-disk/
│   ├── SKILL.md
│   ├── scripts/
│   │   └── download.py
│   └── references/
├── yandex-search/
│   ├── SKILL.md
│   ├── scripts/
│   │   └── search.py
│   └── references/
└── yandex-cloud/
    ├── SKILL.md
    ├── scripts/
    │   └── deploy_function.sh
    └── references/
```

## License

MIT
