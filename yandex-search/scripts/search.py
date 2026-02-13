#!/usr/bin/env python3
"""
Yandex Search — CLI and Python API.

Search the web using Yandex Cloud Search API v2.
Async client with XML response parsing, result optimization, and formatted output.

Core API client logic based on yandex-search by Fedor Kondakov (MIT License).
https://github.com/RawsTourix/yandex-search

Requires: YANDEX_SEARCH_API_KEY and YANDEX_CLOUD_FOLDER_ID environment variables.

Usage:
    python search.py "query text" --count 10 --format json
"""

import os
import sys
import json
import asyncio
import argparse
import logging
import base64
import re
from typing import List, Dict, Optional, Any
from xml.etree import ElementTree as ET

try:
    import aiohttp
except ImportError:
    print("Missing dependency: pip install aiohttp", file=sys.stderr)
    sys.exit(1)


logger = logging.getLogger("YandexSearch")

# ── API Client ────────────────────────────────────────────────────────────────

API_BASE = "https://searchapi.api.cloud.yandex.net"
OPERATIONS_BASE = "https://operation.api.cloud.yandex.net"


async def _search_api(
    api_key: str,
    folder_id: str,
    query_text: str,
    groups_on_page: int = 20,
    pages_to_fetch: List[int] | None = None,
    docs_in_group: int = 1,
    max_passages: int = 5,
    search_type: str = "SEARCH_TYPE_RU",
    family_mode: str = "FAMILY_MODE_MODERATE",
    region: Optional[int] = None,
) -> List[Dict]:
    """Execute async search against Yandex Cloud Search API v2.

    Sends one request per page, polls for completion, parses XML results.
    """
    if pages_to_fetch is None:
        pages_to_fetch = [0]

    headers = {"Authorization": f"Api-Key {api_key}"}

    async with aiohttp.ClientSession(headers=headers) as session:
        # Submit search operations
        operations = []
        for page in pages_to_fetch:
            body = {
                "query": {
                    "search_type": search_type,
                    "query_text": query_text,
                    "family_mode": family_mode,
                    "page": page,
                },
                "sort_spec": {
                    "sort_mode": "SORT_MODE_BY_RELEVANCE",
                    "sort_order": "SORT_ORDER_DESC",
                },
                "group_spec": {
                    "group_mode": "GROUP_MODE_DEEP",
                    "groups_on_page": groups_on_page,
                    "docs_in_group": docs_in_group,
                },
                "max_passages": max_passages,
                "l10n": "LOCALIZATION_RU",
                "folder_id": folder_id,
                "response_format": "FORMAT_XML",
            }
            if region:
                body["region"] = region

            async with session.post(
                f"{API_BASE}/v2/web/searchAsync", json=body
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error(f"Request error: {resp.status} - {error}")
                    continue
                operations.append((await resp.json())["id"])

        # Poll for results
        xml_results = []
        for op_id in operations:
            for attempt in range(10):
                async with session.get(
                    f"{OPERATIONS_BASE}/operations/{op_id}"
                ) as resp:
                    if resp.status != 200:
                        await asyncio.sleep(1)
                        continue
                    operation = await resp.json()
                    if operation.get("done"):
                        xml_results.append(
                            base64.b64decode(
                                operation["response"]["rawData"]
                            ).decode("utf-8")
                        )
                        break
                await asyncio.sleep(1)

        # Parse XML results
        parsed = []
        for xml in xml_results:
            parsed.extend(_parse_xml_results(xml))

        return parsed


# ── XML Parser ────────────────────────────────────────────────────────────────

def _get_element_text(element: Optional[ET.Element]) -> str:
    """Recursively extract all text from an XML element."""
    return ''.join(element.itertext()).strip() if element is not None else ""


def _clean_text(text: str) -> str:
    """Remove HTML/XML tags from text."""
    if not text or '<' not in text:
        return text.strip() if text else ""
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_xml_results(xml_content: str) -> List[Dict]:
    """Parse Yandex Search API XML response into result dicts."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        logger.error(f"XML parse error: {e}")
        return []

    results = []
    for doc in root.iter('doc'):
        try:
            url = doc.findtext('url', '')
            domain = doc.findtext('domain', '')
            title = _clean_text(_get_element_text(doc.find('title')))
            headline = _clean_text(_get_element_text(doc.find('headline')))
            modtime = doc.findtext('modtime', '')

            props = doc.find('properties')
            lang = props.findtext('lang', '') if props else ''

            # Content priority: extended-text > passages > headline
            content = ""
            if props:
                ext = props.find('extended-text')
                if ext is not None:
                    content = _get_element_text(ext)
            if not content:
                passages = [_get_element_text(p) for p in doc.iter('passage')]
                content = " ".join(p for p in passages if p)
            if not content:
                content = headline

            results.append({
                "url": url,
                "domain": domain,
                "title": title,
                "headline": headline,
                "modtime": modtime,
                "lang": lang,
                "content": _clean_text(content),
            })
        except Exception as e:
            logger.error(f"Error parsing doc: {e}")
            continue

    return results


# ── Result Processing ─────────────────────────────────────────────────────────

def optimize_results(
    results: List[Dict], min_length: int = 0
) -> List[Dict]:
    """Filter results by content length."""
    return [r for r in results if r.get("content") and len(r["content"]) > min_length]


def format_results(results: List[Dict], query: str) -> str:
    """Format results as human-readable text."""
    if not results:
        return f"No results for '{query}'"

    lines = [f"Search results for '{query}':"]
    for i, r in enumerate(results):
        lines.append(
            f"\n{i+1}. [{r['domain']}] {r['title']}\n"
            f"   URL: {r['url']}\n"
            f"   Updated: {r.get('modtime', 'N/A')}\n"
            f"   Language: {r.get('lang', 'N/A')}\n"
            f"   Content: {r['content']}"
        )
    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

async def search_async(
    query: str,
    count: int = 10,
    pages: int = 1,
    search_type: str = "SEARCH_TYPE_RU",
    family_mode: str = "FAMILY_MODE_MODERATE",
    region: Optional[int] = None,
    verbose: bool = False,
) -> List[Dict]:
    """Perform async web search. Returns list of result dicts."""
    api_key = os.getenv("YANDEX_SEARCH_API_KEY")
    folder_id = os.getenv("YANDEX_CLOUD_FOLDER_ID")
    if not api_key:
        raise ValueError("YANDEX_SEARCH_API_KEY not set")
    if not folder_id:
        raise ValueError("YANDEX_CLOUD_FOLDER_ID not set")

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    results = await _search_api(
        api_key=api_key,
        folder_id=folder_id,
        query_text=query,
        groups_on_page=count,
        pages_to_fetch=list(range(pages)),
        search_type=search_type,
        family_mode=family_mode,
        region=region,
    )
    return optimize_results(results, min_length=10)


def search(
    query: str,
    count: int = 10,
    pages: int = 1,
    search_type: str = "SEARCH_TYPE_RU",
    family_mode: str = "FAMILY_MODE_MODERATE",
    region: Optional[int] = None,
    verbose: bool = False,
) -> List[Dict]:
    """Synchronous web search wrapper."""
    return asyncio.run(search_async(
        query=query, count=count, pages=pages,
        search_type=search_type, family_mode=family_mode,
        region=region, verbose=verbose,
    ))


# ── CLI ───────────────────────────────────────────────────────────────────────

def format_output(results: List[Dict], query: str, fmt: str = "json") -> str:
    """Format results for CLI output."""
    if fmt == "json":
        return json.dumps({
            "query": query,
            "count": len(results),
            "results": [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "domain": r.get("domain", ""),
                    "snippet": r.get("content", r.get("headline", "")),
                    "lang": r.get("lang", ""),
                    "modtime": r.get("modtime", ""),
                }
                for r in results
            ],
        }, ensure_ascii=False, indent=2)
    return format_results(results, query)


def main():
    parser = argparse.ArgumentParser(
        description="Search Yandex using Cloud Search API v2",
    )
    parser.add_argument("query", help="Search query text")
    parser.add_argument("--count", "-c", type=int, default=10, help="Results per page")
    parser.add_argument("--pages", "-p", type=int, default=1, help="Pages to fetch")
    parser.add_argument(
        "--type", "-t", dest="search_type", default="SEARCH_TYPE_RU",
        choices=["SEARCH_TYPE_RU", "SEARCH_TYPE_COM", "SEARCH_TYPE_TR",
                 "SEARCH_TYPE_KK", "SEARCH_TYPE_BE", "SEARCH_TYPE_UZ"],
    )
    parser.add_argument(
        "--family", "-f", dest="family_mode", default="FAMILY_MODE_MODERATE",
        choices=["FAMILY_MODE_STRICT", "FAMILY_MODE_MODERATE", "FAMILY_MODE_NONE"],
    )
    parser.add_argument("--region", "-r", type=int, help="Region ID")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    try:
        results = search(
            query=args.query, count=args.count, pages=args.pages,
            search_type=args.search_type, family_mode=args.family_mode,
            region=args.region, verbose=args.verbose,
        )
        print(format_output(results, args.query, args.format))
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Search error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
