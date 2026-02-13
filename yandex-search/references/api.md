# Yandex XML Search API Reference

Official API for programmatic web search.

## Getting Started

1. **Register:** https://yandex.com/dev/xml/
2. **Get API key** from dashboard
3. **Set credentials:**
   ```bash
   export YANDEX_SEARCH_API_KEY="your-key-here"
   export YANDEX_SEARCH_USER="your-user-id"
   ```

## Pricing

- **Per query:** ~₽0.30 (approximately $0.003 USD)
- **Free tier:** None (paid from first query)
- **Minimum payment:** ₽1000 (~$10 USD)

## Request Format

### Base URL
```
https://yandex.com/search/xml
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user` | string | Yes | User ID from dashboard |
| `key` | string | Yes | API key |
| `query` | string | Yes | Search query (URL-encoded) |
| `lr` | int | No | Region ID (default: 225) |
| `l10n` | string | No | Language (ru, en, uk, tr) |
| `sortby` | string | No | Sort order (rlv=relevance, tm=time) |
| `filter` | string | No | Filtering (none, moderate, strict) |
| `maxpassages` | int | No | Snippet passages (1-5) |
| `groupby` | string | No | Result grouping parameters |

### Grouping Parameter

Format: `attr=d.mode=MODE.groups-on-page=N.docs-in-group=M`

- `attr=d` — Group by domain
- `mode=deep` — Include all pages from domain
- `mode=flat` — One page per domain
- `groups-on-page=N` — Number of result groups (max 100)
- `docs-in-group=M` — Pages per group (1 for flat)

**Example:**
```
attr=d.mode=deep.groups-on-page=10.docs-in-group=1
```
Returns 10 groups, 1 document each (10 total results).

## Response Format (XML)

```xml
<yandexsearch version="1.0">
  <response>
    <results>
      <grouping>
        <group>
          <doc>
            <url>https://example.com/page</url>
            <domain>example.com</domain>
            <title>Page <hlword>Title</hlword></title>
            <passages>
              <passage>Text with <hlword>query</hlword> terms highlighted...</passage>
            </passages>
          </doc>
        </group>
        <!-- More groups... -->
      </grouping>
    </results>
  </response>
</yandexsearch>
```

## Example Request

```bash
curl "https://yandex.com/search/xml?\
user=YOUR_USER_ID&\
key=YOUR_API_KEY&\
query=artificial+intelligence&\
lr=213&\
l10n=ru&\
sortby=rlv&\
maxpassages=2&\
groupby=attr%3Dd.mode%3Ddeep.groups-on-page%3D10.docs-in-group%3D1"
```

## Rate Limits

- **Per second:** 10 queries (burst)
- **Per hour:** 1000 queries (sustained)
- **Concurrent:** 3 requests

Exceeding limits returns HTTP 429 (Too Many Requests).

## Error Codes

| Code | Meaning |
|------|---------|
| 15 | Invalid API key |
| 20 | Insufficient funds |
| 31 | Invalid region ID |
| 32 | Invalid grouping parameter |
| 33 | Invalid query format |
| 48 | Rate limit exceeded |

## Advanced Features

### Date Filtering

Add to query:
- `date:YYYYMMDD..YYYYMMDD` — Date range
- `date:today` — Today only
- `date:week` — Past week
- `date:month` — Past month

Example: `query date:20240101..20241231`

### Site-Specific Search

Add to query: `site:example.com query`

### File Type Filtering

Add to query: `query filetype:pdf`

Supported: pdf, doc, docx, xls, xlsx, ppt, pptx, txt

### Language Detection

API automatically detects query language. Override with `l10n` parameter.

## Best Practices

1. **Cache results** — Store for repeated queries
2. **Batch requests** — Group similar queries when possible
3. **Error handling** — Retry with exponential backoff
4. **Monitor usage** — Track API call count
5. **Sanitize queries** — URL-encode special characters

## Comparison with Alternatives

| Feature | Yandex XML | Google CSE | Bing Search |
|---------|------------|------------|-------------|
| Russian content | ⭐⭐⭐ | ⭐⭐ | ⭐ |
| Cost per 1K queries | ~$3 | ~$5 | ~$7 |
| Free tier | ❌ | ✅ (100/day) | ✅ (1000/mo) |
| Regional targeting | Excellent | Good | Good |
| Setup complexity | Medium | Low | Medium |

## Using in Python

See `scripts/search.py` for complete implementation.

**Quick example:**
```python
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

params = {
    'user': 'YOUR_USER_ID',
    'key': 'YOUR_API_KEY',
    'query': 'search query',
    'lr': 213,
    'l10n': 'ru',
    'groupby': 'attr=d.mode=deep.groups-on-page=10.docs-in-group=1'
}

url = f"https://yandex.com/search/xml?{urlencode(params)}"
response = requests.get(url)
root = ET.fromstring(response.content)

for group in root.findall('.//group'):
    doc = group.find('doc')
    title = doc.find('title').text
    url = doc.find('url').text
    print(f"{title}: {url}")
```

## Official Documentation

- **API docs:** https://yandex.com/dev/xml/doc/
- **Region codes:** https://yandex.com/dev/xml/doc/dg/reference/regions.html
- **Dashboard:** https://xml.yandex.com/
- **Support:** xml@yandex-team.ru

## Troubleshooting

**"Invalid key" error:**
- Verify API key copied correctly (no spaces)
- Check key is active in dashboard
- Ensure funds available

**Empty results:**
- Check query encoding (URL-safe)
- Try broader region (225 instead of city)
- Verify language setting

**Rate limit errors:**
- Implement exponential backoff
- Cache frequently accessed results
- Consider query batching

**Parsing errors:**
- Check XML response format
- Handle missing fields gracefully
- Log raw XML for debugging
