# Telegram + Yandex Cloud Patterns

Common patterns for integrating Telegram bots with Yandex Cloud serverless infrastructure.

## Pattern 1: Scheduled Message Fetcher (Daily Digest)

**Use case:** Fetch messages from Telegram channels daily and process them.

**Architecture:**
```
Yandex Cloud Timer (cron)
    ↓
Cloud Function
    ↓ download session
Object Storage (session.db)
    ↑ upload session
    ↓
Telegram API (via Telethon)
    ↓
Process & deliver results
```

**Key considerations:**
- Session must be downloaded before connecting
- Session must be uploaded after disconnecting
- Handle session expiry (re-auth needed ~yearly)
- Use async I/O to avoid timeouts

**Implementation:**

```python
import os
import boto3
from io import BytesIO
from telethon import TelegramClient
from telethon.sessions import StringSession

# Object Storage setup
s3 = boto3.client(
    's3',
    endpoint_url='https://storage.yandexcloud.net',
    aws_access_key_id=os.getenv('YC_ACCESS_KEY'),
    aws_secret_access_key=os.getenv('YC_SECRET_KEY')
)

BUCKET = os.getenv('TELEGRAM_SESSION_BUCKET', 'telegram-sessions')
SESSION_KEY = 'digest.session'

async def fetch_messages(channels, hours=24):
    """Fetch messages from channels from last N hours"""
    from datetime import datetime, timedelta
    
    # Download session
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=SESSION_KEY)
        session_string = obj['Body'].read().decode()
    except:
        raise Exception("Session not found. Run auth locally first.")
    
    # Connect with existing session
    client = TelegramClient(
        StringSession(session_string),
        api_id=os.getenv('TG_API_ID'),
        api_hash=os.getenv('TG_API_HASH')
    )
    
    await client.connect()
    
    if not await client.is_user_authorized():
        raise Exception("Session expired. Re-auth needed.")
    
    # Fetch messages
    cutoff = datetime.now() - timedelta(hours=hours)
    all_messages = []
    
    for channel in channels:
        async for message in client.iter_messages(channel, offset_date=cutoff):
            all_messages.append({
                'channel': channel,
                'text': message.text,
                'date': message.date,
                'id': message.id
            })
    
    # Save session (in case of updates)
    session_string = client.session.save()
    s3.put_object(
        Bucket=BUCKET,
        Key=SESSION_KEY,
        Body=session_string.encode()
    )
    
    await client.disconnect()
    
    return all_messages

def handler(event, context):
    import asyncio
    
    channels = [
        'https://t.me/channel1',
        'https://t.me/channel2'
    ]
    
    messages = asyncio.run(fetch_messages(channels, hours=24))
    
    return {
        'statusCode': 200,
        'body': f'Fetched {len(messages)} messages'
    }
```

**Local auth script** (run once):

```python
# auth_local.py
from telethon import TelegramClient
from telethon.sessions import StringSession
import boto3
import os

# Object Storage
s3 = boto3.client(
    's3',
    endpoint_url='https://storage.yandexcloud.net',
    aws_access_key_id=os.getenv('YC_ACCESS_KEY'),
    aws_secret_access_key=os.getenv('YC_SECRET_KEY')
)

api_id = int(os.getenv('TG_API_ID'))
api_hash = os.getenv('TG_API_HASH')
phone = os.getenv('TG_PHONE')

async def main():
    client = TelegramClient(StringSession(), api_id, api_hash)
    
    await client.connect()
    
    if not await client.is_user_authorized():
        await client.send_code_request(phone)
        code = input('Enter code: ')
        await client.sign_in(phone, code)
    
    session_string = client.session.save()
    
    # Upload to Object Storage
    s3.put_object(
        Bucket='telegram-sessions',
        Key='digest.session',
        Body=session_string.encode()
    )
    
    print(f"✅ Session uploaded to Object Storage")
    
    await client.disconnect()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
```

## Pattern 2: Webhook Bot (Interactive)

**Use case:** Respond to user messages in real-time.

**Architecture:**
```
Telegram Bot API
    ↓ webhook
API Gateway
    ↓ trigger
Cloud Function
    ↓ process & respond
Telegram Bot API
```

**Key considerations:**
- No session persistence needed (bot token-based)
- Response must be within 60 seconds
- Use `aiogram` or `python-telegram-bot` library

**Implementation:**

```python
import os
import json
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters

bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
bot = Bot(token=bot_token)

async def start(update: Update, context):
    await update.message.reply_text('Hello!')

async def process_webhook(update_json):
    update = Update.de_json(update_json, bot)
    
    # Handle commands
    if update.message and update.message.text:
        if update.message.text == '/start':
            await start(update, None)
        else:
            await update.message.reply_text(f'Echo: {update.message.text}')

def handler(event, context):
    import asyncio
    
    # Parse webhook payload
    body = json.loads(event['body'])
    
    asyncio.run(process_webhook(body))
    
    return {
        'statusCode': 200,
        'body': 'ok'
    }
```

**Set webhook** (run once):

```bash
curl -X POST https://api.telegram.org/bot<TOKEN>/setWebhook \
  -d "url=https://<function-url>"
```

## Pattern 3: Hybrid (Scheduled + Webhook)

**Use case:** Daily digest + interactive commands.

**Architecture:**
- Function 1 (cron): Fetch & process daily
- Function 2 (webhook): Handle user commands
- Shared: Object Storage for state

## Session Management Best Practices

### 1. Use StringSession for cloud functions

```python
from telethon.sessions import StringSession

# Good: Serializable, no file I/O
client = TelegramClient(StringSession(), api_id, api_hash)
session_str = client.session.save()

# Bad: Requires file system
client = TelegramClient('session.db', api_id, api_hash)
```

### 2. Always check authorization before API calls

```python
await client.connect()

if not await client.is_user_authorized():
    raise Exception("Session expired - re-auth needed")

# Now safe to make API calls
messages = await client.get_messages('channel')
```

### 3. Handle rate limits

```python
from telethon.errors import FloodWaitError
import asyncio

try:
    messages = await client.get_messages('channel')
except FloodWaitError as e:
    print(f"Rate limited for {e.seconds} seconds")
    await asyncio.sleep(e.seconds)
    messages = await client.get_messages('channel')
```

### 4. Use connection pooling for multiple requests

```python
async with client:
    # Connection stays open
    for channel in channels:
        messages = await client.get_messages(channel)
        # Process messages
    # Connection closes automatically
```

## Debugging

### Check if session is valid

```python
import boto3

s3 = boto3.client('s3', endpoint_url='https://storage.yandexcloud.net')
obj = s3.get_object(Bucket='telegram-sessions', Key='digest.session')
session_str = obj['Body'].read().decode()

print(f"Session length: {len(session_str)} chars")
print(f"Session preview: {session_str[:50]}...")
```

### Test function locally

```python
# test_local.py
from handler import handler

event = {}
context = {}

result = handler(event, context)
print(result)
```

### View Yandex Cloud Function logs

```bash
yc serverless function logs <function-id> --follow
```

## Troubleshooting

**"Session expired":**
- Session typically valid for ~1 year
- Re-run auth script locally
- Upload new session to Object Storage

**"FloodWaitError":**
- Telegram rate limit hit
- Wait specified seconds before retry
- Reduce request frequency

**"ConnectionError":**
- Yandex Cloud Function timeout (default 3s)
- Increase timeout: `--execution-timeout 5m`
- Use async I/O to speed up

**Session not persisting:**
- Check `client.session.save()` called after operations
- Verify S3 upload succeeds (check logs)
- Ensure session downloaded before `TelegramClient()` init
