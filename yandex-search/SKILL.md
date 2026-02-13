---
name: yandex-search
description: >
  Search the web using Yandex Cloud Search API v2. Supports async queries
  with regional targeting, content filtering, and structured output.
  Use when Russian-language search results are preferred or when Western
  search APIs are unavailable.
license: MIT
compatibility: Requires Python 3.10+, aiohttp, network access to Yandex Cloud API
metadata:
  author: bizyumov
  version: "1.0"
---

# Yandex Search

## Overview

Perform web searches using Yandex Cloud Search API v2. This skill uses an async Python client for optimal performance and supports multiple search types, family filtering, and regional targeting.

## Quick Start

**Basic search:**
```bash
python scripts/search.py "query text"
```

**With options:**
```bash
python scripts/search.py "query" --count 20 --type SEARCH_TYPE_RU --format text
```

**From Python:**
```python
from scripts.search import search

results = search("query text", count=10)
for result in results:
    print(f"{result['title']}: {result['url']}")
```

## Environment Variables

Required environment variables:

```bash
YANDEX_SEARCH_API_KEY    # API key from Yandex Cloud service account
YANDEX_CLOUD_FOLDER_ID   # Folder ID from Yandex Cloud console
```

See `SETUP.md` for detailed setup instructions.

## CLI Usage

```bash
python scripts/search.py "query" [options]
```

### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--count N` | `-c` | 10 | Results per page (1-100) |
| `--pages N` | `-p` | 1 | Number of pages to fetch |
| `--type TYPE` | `-t` | SEARCH_TYPE_RU | Search type |
| `--family MODE` | `-f` | FAMILY_MODE_MODERATE | Content filter |
| `--region ID` | `-r` | None | Region ID for geo-targeting |
| `--format FMT` | | json | Output format (json/text) |
| `--verbose` | `-v` | False | Enable debug logging |

### Search Types

| Type | Description |
|------|-------------|
| `SEARCH_TYPE_RU` | Russian search (default) |
| `SEARCH_TYPE_COM` | International search |
| `SEARCH_TYPE_TR` | Turkish search |
| `SEARCH_TYPE_KK` | Kazakh search |
| `SEARCH_TYPE_BE` | Belarusian search |
| `SEARCH_TYPE_UZ` | Uzbek search |

### Family Filter Modes

| Mode | Description |
|------|-------------|
| `FAMILY_MODE_STRICT` | Strict filtering of adult content |
| `FAMILY_MODE_MODERATE` | Moderate filtering (default) |
| `FAMILY_MODE_NONE` | No filtering |

### Region Codes

Common Yandex region IDs:
- `213` — Moscow
- `2` — St. Petersburg
- `54` — Yekaterinburg
- `65` — Novosibirsk
- `11316` — Kazan
- `225` — Russia (country-wide)

See `references/regions.md` for complete list.

## Output Format

### JSON (default)

```json
{
  "query": "artificial intelligence",
  "count": 10,
  "results": [
    {
      "title": "Page title",
      "url": "https://example.com/page",
      "domain": "example.com",
      "snippet": "Page description or content excerpt...",
      "lang": "ru",
      "modtime": "20260101T120000"
    }
  ]
}
```

### Text

```
Результаты поиска по 'artificial intelligence':

1. [example.com] Page Title
   URL: https://example.com/page
   Обновлено: 20260101T120000
   Язык: ru
   Контент: Page description or content excerpt...
```

## Python API

### Synchronous Search

```python
from scripts.search import search

results = search(
    query="machine learning",
    count=20,           # Results per page
    pages=2,            # Fetch 2 pages (2 API requests)
    search_type="SEARCH_TYPE_RU",
    family_mode="FAMILY_MODE_MODERATE",
    region=213,         # Moscow
    verbose=False
)

for r in results:
    print(f"{r['title']}: {r['url']}")
```

### Async Search

```python
import asyncio
from scripts.search import search_async

async def main():
    results = await search_async(
        query="python async",
        count=10,
        pages=1
    )
    return results

results = asyncio.run(main())
```

### Direct API Function Usage

```python
import asyncio
import os
from scripts.search import _search_api, optimize_results, format_results

async def main():
    results = await _search_api(
        api_key=os.getenv("YANDEX_SEARCH_API_KEY"),
        folder_id=os.getenv("YANDEX_CLOUD_FOLDER_ID"),
        query_text="python tutorial",
        groups_on_page=20,
        pages_to_fetch=[0, 1],
        docs_in_group=1,
        max_passages=5,
    )

    optimized = optimize_results(results, min_length=30)
    print(format_results(optimized, "python tutorial"))

asyncio.run(main())
```

## API Parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `query_text` | Required | Up to 400 chars | Search query |
| `groups_on_page` | 20 | 1-100 | Results per page |
| `pages_to_fetch` | [0] | 0+ | List of page indices |
| `docs_in_group` | 1 | 1-3 | Documents per domain group |
| `max_passages` | 5 | 1-5 | Text snippets per result |

## Result Fields

Each result contains:
- `url` — Page URL
- `domain` — Site domain
- `title` — Page title
- `headline` — Brief description
- `content` — Main text content (from passages or extended-text)
- `modtime` — Last update time (YYYYMMDDThhmmss)
- `lang` — Content language

## Cost and Billing

**Pricing:** ~0.30 RUB per query (~$0.003 USD)

Each page in `pages_to_fetch` counts as a separate API request.

**Optimization tips:**
- Use `groups_on_page=100` to get more results per request
- Use `docs_in_group=3` for up to 300 results per request
- Cache results when possible

## Use Cases

**When to use Yandex Search:**
- Searching Russian-language content
- Region-specific results (Russia, CIS countries)
- When Western search APIs are unavailable
- Technical documentation in Russian

**When to use alternatives:**
- English-language searches → Brave/Perplexity
- AI-synthesized answers → Perplexity
- Free tier preference → Brave

## Files

- `scripts/search.py` — Self-contained CLI + Python API (inline async client)
- `references/regions.md` — Complete list of Yandex region codes
- `references/api.md` — API documentation reference
- `SETUP.md` — Step-by-step Yandex Cloud account setup

## Troubleshooting

**"Configuration error: YANDEX_SEARCH_API_KEY..."**
- Set required environment variables
- See SETUP.md for configuration

**Empty results:**
- Try broader query
- Check search type matches content language
- Use `--verbose` for debug info

**Rate limiting:**
- API has high limits but costs per query
- Monitor usage in Yandex Cloud Console

## Resources

- **API Docs:** https://yandex.cloud/ru/docs/search-api/
- **Original attribution:** Core API logic based on yandex-search by Fedor Kondakov (MIT)
- **Setup guide:** SETUP.md
