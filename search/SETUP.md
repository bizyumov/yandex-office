# Yandex Search API Setup Guide

Step-by-step instructions to enable web search via Yandex Cloud Search API v2.

## Prerequisites

- Python 3.7+ (recommended: 3.11+)
- `aiohttp` and `python-dotenv` packages
- Yandex Cloud account

## Step 1: Install Dependencies

```bash
pip install aiohttp python-dotenv
```

## Step 2: Create Yandex Cloud Account

1. Go to https://cloud.yandex.ru/ (or https://cloud.yandex.com/ for English)
2. Click **"Try for free"** or **"Console"**
3. Log in with Yandex account (register at https://passport.yandex.ru/ if needed)
4. Accept terms of service
5. Verify phone number if prompted
6. Create a billing account:
   - **Individual** — for personal use
   - **Business** — for company use

**Free trial:** 4000 RUB credits (~$40) for 60 days

## Step 3: Create a Folder

1. In Yandex Cloud Console, go to **"Catalog"** (Каталоги)
2. Create a new folder or use the default one
3. **Copy the Folder ID** — you'll need it for API configuration

## Step 4: Create Service Account

1. In Cloud Console sidebar, click **"Service accounts"** (Сервисные аккаунты)
2. Click **"Create service account"**
3. Fill in:
   - **Name:** `search-api-bot` (or any name)
   - **Description:** (optional)
4. Click **"Create"**

## Step 5: Grant Roles to Service Account

1. Select the service account you just created
2. Click **"Roles"** tab
3. Click **"Assign roles"**
4. Add role: **`search-api.editor`** or **`search-api.admin`**
5. Click **"Save"**

## Step 6: Create API Key

### Option A: Via Cloud Console

1. In Service Account page, go to **"API keys"** tab
2. Click **"Create API key"**
3. Add description (optional)
4. Click **"Create"**
5. **IMPORTANT:** Copy the secret key immediately — you won't see it again!

### Option B: Via Cloud Shell (CLI)

```bash
# Set your service account ID
export SERVICEACCOUNT_ID=<your_service_account_id>

# Get IAM token
export IAM_TOKEN=$(yc iam create-token)

# Create API key
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IAM_TOKEN" \
  -d '{
    "serviceAccountId": "'"$SERVICEACCOUNT_ID"'",
    "description": "API key for Search API"
  }' \
  https://iam.api.cloud.yandex.net/iam/v1/apiKeys
```

Save the `secret` field from the response — this is your API key.

> **Note:** The IAM token is only valid for 12 hours, but you only need it once to create the API key.

## Step 7: Configure Environment Variables

Add to `~/.openclaw/.env`:

```bash
# Yandex Cloud Search API credentials
YANDEX_SEARCH_API_KEY="<your_api_key_secret>"
YANDEX_CLOUD_FOLDER_ID="<your_folder_id>"
```

Or export in shell:

```bash
export YANDEX_SEARCH_API_KEY="<your_api_key_secret>"
export YANDEX_CLOUD_FOLDER_ID="<your_folder_id>"
```

## Step 8: Test the API

```bash
python3 scripts/search.py "yandex cloud tutorial" --count 3
```

Expected output: JSON with search results.

For text format:

```bash
python3 scripts/search.py "python async" --count 5 --format text
```

## Troubleshooting

### "YANDEX_SEARCH_API_KEY environment variable not set"

**Fix:** Ensure environment variables are set correctly:
```bash
echo $YANDEX_SEARCH_API_KEY
echo $YANDEX_CLOUD_FOLDER_ID
```

### "403 Forbidden" or "Access Denied"

**Causes:**
- Service account missing `search-api.editor` role
- API key invalid or expired
- Search API service not activated

**Fix:**
1. Check service account roles in Cloud Console
2. Verify API key copied correctly (no spaces)
3. Ensure Search API is activated in your folder

### "Payment required" or billing error

**Causes:**
- Free trial expired
- No payment method attached
- Insufficient balance

**Fix:**
1. Go to **"Billing"** in Cloud Console
2. Add payment method (card)
3. Top up balance (minimum 1000 RUB)

### Empty results but no error

**Causes:**
- Query too specific
- Wrong search type for content language
- Regional filtering too narrow

**Fix:**
- Try broader query
- Use `--type SEARCH_TYPE_RU` for Russian content
- Use `--type SEARCH_TYPE_COM` for international content
- Omit `--region` or use appropriate region ID

### Connection errors

**Causes:**
- Network issues
- API endpoint unavailable

**Fix:**
- Check internet connection
- Try again later
- Use `--verbose` flag for detailed error info

## Cost Estimates

**Pricing:** ~0.30 RUB per query (~$0.003 USD)

**Light usage (testing):**
- 100 queries/day = 30 RUB/day = 900 RUB/month (~$9)

**Medium usage (daily digest):**
- 10 queries/day = 3 RUB/day = 90 RUB/month (~$0.90)

**Free trial covers:** ~13,000 queries (4000 RUB / 0.30 RUB)

## API Documentation

- **Official docs (RU):** https://yandex.cloud/ru/docs/search-api/
- **Official docs (EN):** https://yandex.cloud/en/docs/search-api/
- **API reference:** https://yandex.cloud/ru/docs/search-api/operations/web-search
- **Support:** https://cloud.yandex.com/support

---

**Updated:** 2026-02-03
**For:** OpenClaw Yandex Search skill
