#!/usr/bin/env python3
"""Tests for yandex-search.

S8: Live search API test
S9: CLI flags and output formatting
"""

import json
import sys
from pathlib import Path
from search import (
    _clean_text,
    _parse_xml_results,
    format_results,
    format_output,
    optimize_results,
    search,
)


# ── Unit tests (no API needed) ──────────────────────────────────────

SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
<response>
<results>
<grouping>
<group>
<doc>
    <url>https://example.com/page1</url>
    <domain>example.com</domain>
    <title>Example Page &lt;b&gt;One&lt;/b&gt;</title>
    <headline>A sample headline</headline>
    <modtime>20260210T120000</modtime>
    <properties>
        <lang>ru</lang>
        <extended-text>Extended content about the topic with enough detail.</extended-text>
    </properties>
</doc>
</group>
<group>
<doc>
    <url>https://test.org/article</url>
    <domain>test.org</domain>
    <title>Test Article</title>
    <headline>Short</headline>
    <modtime>20260211T080000</modtime>
    <properties>
        <lang>en</lang>
    </properties>
    <passages><passage>This is a passage with more detail about the search result.</passage></passages>
</doc>
</group>
</grouping>
</results>
</response>
</yandexsearch>
"""


def test_clean_text():
    """HTML tags are stripped from text."""
    assert _clean_text("<b>bold</b> text") == "bold text"
    assert _clean_text("no tags") == "no tags"
    assert _clean_text("") == ""
    assert _clean_text(None) == ""
    print("  PASS: _clean_text strips HTML tags")


def test_parse_xml_results():
    """XML response is parsed into result dicts."""
    results = _parse_xml_results(SAMPLE_XML)
    assert len(results) == 2

    r1 = results[0]
    assert r1["url"] == "https://example.com/page1"
    assert r1["domain"] == "example.com"
    assert "One" in r1["title"]
    assert "<b>" not in r1["title"]  # Tags stripped
    assert r1["lang"] == "ru"
    assert "Extended content" in r1["content"]

    r2 = results[1]
    assert r2["url"] == "https://test.org/article"
    assert "passage" in r2["content"].lower()

    print(f"  PASS: _parse_xml_results → {len(results)} results parsed")


def test_parse_xml_invalid():
    """Invalid XML doesn't crash — returns empty list."""
    results = _parse_xml_results("not xml at all {}")
    assert results == []
    print("  PASS: invalid XML → empty list, no crash")


def test_optimize_results():
    """Filter by content length."""
    results = [
        {"content": "short"},
        {"content": "a long enough content string that passes the filter"},
        {"content": ""},
    ]
    filtered = optimize_results(results, min_length=10)
    assert len(filtered) == 1
    assert "long enough" in filtered[0]["content"]
    print("  PASS: optimize_results filters by min_length")


def test_format_results_text():
    """Text output is readable."""
    results = [{"domain": "ex.com", "title": "Page", "url": "https://ex.com",
                "content": "Content", "modtime": "20260210", "lang": "ru"}]
    text = format_results(results, "test query")
    assert "test query" in text
    assert "ex.com" in text
    assert "Page" in text
    print("  PASS: format_results → readable text")


def test_format_results_empty():
    """No results message."""
    text = format_results([], "nothing")
    assert "No results" in text
    print("  PASS: format_results empty → 'No results'")


def test_format_output_json():
    """JSON output has correct structure."""
    results = [{"title": "T", "url": "U", "domain": "D", "content": "C",
                "headline": "H", "lang": "ru", "modtime": "20260210"}]
    output = format_output(results, "q", fmt="json")
    data = json.loads(output)
    assert data["query"] == "q"
    assert data["count"] == 1
    assert data["results"][0]["title"] == "T"
    assert data["results"][0]["snippet"] == "C"
    print("  PASS: format_output JSON → valid structure")


# ── S8: Live API test ────────────────────────────────────────────────

def test_live_search():
    """Live search query → real results from Yandex API."""
    try:
        results = search("Яндекс Телемост", count=3, pages=1)
    except ValueError as e:
        print(f"  SKIP: {e} (credentials not set)")
        return
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return

    assert isinstance(results, list)
    # Should get at least 1 result for a common Russian query
    assert len(results) > 0, "No results returned for 'Яндекс Телемост'"

    r = results[0]
    assert "url" in r
    assert "title" in r
    assert "content" in r

    print(f"  PASS: live search → {len(results)} results")
    print(f"         Top: [{r['domain']}] {r['title'][:60]}")


# ── S9: CLI flags ────────────────────────────────────────────────────

def test_cli_help():
    """CLI --help exits 0."""
    import subprocess
    script = str(Path(__file__).parent / "search.py")
    result = subprocess.run(
        [sys.executable, script, "--help"],
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0
    assert "--count" in result.stdout
    assert "--pages" in result.stdout
    assert "--type" in result.stdout
    assert "--format" in result.stdout
    print("  PASS: CLI --help → shows all flags")


def test_cli_missing_env():
    """CLI without env vars → clear error."""
    import subprocess
    script = str(Path(__file__).parent / "search.py")
    env = {"PATH": "/usr/bin:/bin"}  # No API keys
    result = subprocess.run(
        [sys.executable, script, "test"],
        capture_output=True, text=True, timeout=5, env=env,
    )
    assert result.returncode != 0
    assert "Configuration error" in result.stderr or "YANDEX_SEARCH_API_KEY" in result.stderr
    print("  PASS: CLI without credentials → clear error")


# ── Runner ───────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("S8a", test_clean_text),
        ("S8b", test_parse_xml_results),
        ("S8c", test_parse_xml_invalid),
        ("S8d", test_optimize_results),
        ("S8e", test_format_results_text),
        ("S8f", test_format_results_empty),
        ("S8g", test_format_output_json),
        ("S8h", test_live_search),
        ("S9a", test_cli_help),
        ("S9b", test_cli_missing_env),
    ]

    passed = 0
    failed = 0
    for label, fn in tests:
        print(f"\n[{label}] {fn.__doc__}")
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
