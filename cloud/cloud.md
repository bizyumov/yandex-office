---
name: cloud
description: Cloud / Облако — deploy and manage serverless functions, object storage, and cloud resources on Yandex Cloud. Covers deployment patterns, Cloud Functions, Object Storage (S3-compatible), and Yandex Cloud CLI usage. Use when deploying to Yandex Cloud or managing Russian cloud infrastructure.
license: MIT
compatibility: Requires yc CLI, network access to Yandex Cloud
metadata:
  author: bizyumov
  version: "2026.04.10"
---

# Yandex Cloud / Облако

## Overview

Yandex Cloud is a Russian cloud provider offering serverless functions, object storage, and managed services. This skill covers deploying serverless applications, managing state in object storage, and working with the Yandex Cloud CLI (`yc`).

## Core Capabilities

### 1. Serverless Functions (Cloud Functions)

Deploy Python or Node.js functions that run on demand without managing servers.

**Key features:**
- Python 3.12, 3.11, 3.9 / Node.js 18, 16 runtime support
- Triggers: HTTP, Object Storage, Message Queue, Timer (cron)
- Execution timeout: up to 10 minutes
- Memory: 128 MB to 4 GB
- Region: ru-central1 (Moscow)

**Typical workflow:**
1. Write function code (handler)
2. Package dependencies
3. Deploy via CLI or console
4. Configure triggers
5. Monitor logs

### 2. Object Storage (S3-compatible)

Store files, session data, and backups. Compatible with AWS S3 API.

**Use cases:**
- Store Telegram session files (SQLite, ~5KB)
- Backup data
- Static website hosting
- Data lakes

**Access methods:**
- AWS SDK (boto3) with Yandex endpoint
- Yandex CLI (`yc storage`)
- Web console

### 3. Secrets Manager

Store API keys, tokens, and session data securely.

**Alternatives:**
- Environment variables (for non-sensitive config)
- Object Storage (for larger files like sessions)
- Lockbox (Yandex's secrets service)

## Serverless Deployment Pattern

### Basic Python Function

**handler.py:**
```python
def handler(event, context):
    """
    event: dict with request data
    context: execution context (request_id, etc.)
    """
    return {
        'statusCode': 200,
        'body': 'Hello from Yandex Cloud'
    }
```

### With Dependencies

**Structure:**
```
my-function/
├── handler.py
├── requirements.txt
└── lib/  # Dependencies installed here
```

**Deploy:**
```bash
# Install dependencies
pip install -r requirements.txt -t ./lib

# Create zip
zip -r function.zip handler.py lib/

# Deploy
yc serverless function version create \
  --function-name my-function \
  --runtime python312 \
  --entrypoint handler.handler \
  --memory 128m \
  --execution-timeout 10s \
  --source-path function.zip
```

### Stateful Serverless Pattern (for Telegram bots)

**Problem:** Serverless functions are stateless. Telegram requires persistent session.

**Solution:** Store session in Object Storage.

**handler.py:**
```python
import os
import boto3
from io import BytesIO
from telethon import TelegramClient

# S3 client for Yandex Object Storage
s3 = boto3.client(
    's3',
    endpoint_url='https://storage.yandexcloud.net',
    aws_access_key_id=os.getenv('YC_ACCESS_KEY'),
    aws_secret_access_key=os.getenv('YC_SECRET_KEY')
)

BUCKET = 'my-sessions'
SESSION_KEY = 'telegram.session'

def download_session():
    """Download session from Object Storage"""
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=SESSION_KEY)
        return obj['Body'].read()
    except s3.exceptions.NoSuchKey:
        return None

def upload_session(session_data):
    """Upload session to Object Storage"""
    s3.put_object(
        Bucket=BUCKET,
        Key=SESSION_KEY,
        Body=session_data
    )

def handler(event, context):
    # Download existing session
    session_data = download_session()
    
    # Create client with session
    client = TelegramClient(
        BytesIO(session_data) if session_data else 'session',
        api_id=os.getenv('TG_API_ID'),
        api_hash=os.getenv('TG_API_HASH')
    )
    
    async with client:
        # Do work (fetch messages, etc.)
        messages = await client.get_messages('channel')
    
    # Save session back
    upload_session(client.session.save())
    
    return {'statusCode': 200}
```

### Cron Trigger (Timer)

Deploy function with scheduled execution:

```bash
yc serverless trigger create timer \
  --name daily-digest \
  --cron-expression '0 5 * * ? *' \  # 8:00 AM MSK (UTC+3)
  --invoke-function-name my-function \
  --invoke-function-service-account-id <sa-id>
```

**Cron format:** `<minutes> <hours> <day-of-month> <month> <day-of-week> <year>`

Example: `0 5 * * ? *` = 05:00 UTC daily (08:00 MSK)

## Yandex CLI (yc)

### Installation

```bash
# Linux/macOS
curl -sSL https://storage.yandexcloud.net/yandexcloud-yc/install.sh | bash

# Init
yc init
```

### Authentication

**Via OAuth token:**
```bash
yc config set token <OAUTH_TOKEN>
```

**Via service account key:**
```bash
yc config set service-account-key key.json
```

### Common Commands

```bash
# List functions
yc serverless function list

# Get function details
yc serverless function get <function-id>

# View logs
yc serverless function logs <function-id>

# Invoke function
yc serverless function invoke <function-id> --data '{"key":"value"}'

# List buckets
yc storage bucket list

# List objects
yc storage object list --bucket my-bucket
```

## Environment Variables

Set via CLI during deployment:

```bash
yc serverless function version create \
  --function-name my-function \
  --runtime python312 \
  --entrypoint handler.handler \
  --memory 256m \
  --execution-timeout 30s \
  --environment API_KEY=secret123,DEBUG=true \
  --source-path function.zip
```

Or via web console: Functions → select function → Editor → Environment variables.

## Service Accounts

Functions need service accounts to access other Yandex Cloud services.

**Create service account:**
```bash
yc iam service-account create --name my-sa

# Grant roles
yc resource-manager folder add-access-binding <folder-id> \
  --role storage.editor \
  --subject serviceAccount:<sa-id>
```

**Use in function:**
```bash
yc serverless function version create \
  --service-account-id <sa-id> \
  ...
```

## Logging

**View logs:**
```bash
yc serverless function logs <function-id> --follow
```

**In code:**
```python
import logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handler(event, context):
    logger.info('Processing request')
    return {'statusCode': 200}
```

Logs appear in Cloud Logging automatically.

## Pricing (approximate)

- **Cloud Functions:**
  - First 1M invocations: free
  - Then: ~$0.04 per 1M invocations
  - Compute: ~$1.50 per 1M GB-seconds

- **Object Storage:**
  - First 10 GB: free
  - Then: ~$0.02 per GB/month

- **Egress traffic:** ~$0.02 per GB

Costs are minimal for light usage (daily digest = ~$1-2/month).

## Common Patterns

### Pattern: Telegram Digest (Daily Scheduled)

1. Deploy function with Telegram fetching code
2. Store session in Object Storage
3. Configure cron trigger (daily 8:00 AM MSK)
4. Function loads session → fetches → saves session → sends digest

See `scripts/deploy_function.sh` for a generic deployment script.

### Pattern: HTTP API

1. Deploy function
2. Create HTTP trigger (API Gateway integration)
3. Function receives HTTP requests via `event['httpMethod']`, `event['body']`

### Pattern: Object Storage Trigger

1. Deploy function
2. Create Object Storage trigger on bucket events
3. Function processes uploaded files automatically

## Regions

Yandex Cloud has 3 regions:
- **ru-central1** (Moscow) — primary, most services
- **ru-central2** (Moscow) — additional
- **ru-west-1** (St. Petersburg) — beta

Default: `ru-central1-a` (availability zone a).

## Integration with OpenClaw

**Option 1: Direct invocation**
```bash
yc serverless function invoke <function-id>
```

**Option 2: HTTP trigger + webhook**
```bash
curl https://<function-url> -d '{"action":"fetch"}'
```

**Option 3: OpenClaw cron → HTTP call**
Use OpenClaw's `cron` tool to schedule HTTP requests to function endpoint.

## Troubleshooting

**"Access Denied" on Object Storage:**
- Check service account has `storage.editor` role
- Verify access key/secret key are correct

**"Function timeout":**
- Increase `--execution-timeout` (max 10 minutes)
- Optimize code (async I/O, connection pooling)

**"Import error" in function:**
- Verify all dependencies in `lib/` folder
- Check runtime version matches local Python version

**Session not persisting:**
- Verify session upload succeeds (check logs)
- Ensure session downloaded before client init

## Resources

### scripts/
- `deploy_function.sh` — Generic serverless function deployment script

### references/
- `api.md` — Yandex Cloud API reference (yc CLI, REST, Python SDK)
- `patterns.md` — Serverless patterns (scheduled tasks, webhooks, state management)
