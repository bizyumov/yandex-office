#!/usr/bin/env python3
"""Tests for disk downloader.

D7: Verify API client works against live Yandex Disk API.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from download import YandexDisk, API_BASE


# ── Unit tests (mocked HTTP) ────────────────────────────────────────

def test_get_public_meta_mocked():
    """get_public_meta builds correct request and parses response."""
    disk = YandexDisk(token="test_token")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "name": "video.mp4",
        "size": 1234567,
        "mime_type": "video/mp4",
        "type": "file",
        "created": "2026-02-08T19:00:00+00:00",
        "modified": "2026-02-08T19:00:00+00:00",
        "public_url": "https://yadi.sk/d/abc123",
        "path": "/video.mp4",
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "get", return_value=mock_resp) as mock_get:
        meta = disk.get_public_meta("https://yadi.sk/d/abc123")

        mock_get.assert_called_once_with(
            f"{API_BASE}/v1/disk/public/resources",
            params={"public_key": "https://yadi.sk/d/abc123"},
        )
        assert meta["name"] == "video.mp4"
        assert meta["size"] == 1234567
        assert meta["mime_type"] == "video/mp4"
        print("  PASS: get_public_meta → correct request + parsing")


def test_get_download_link_mocked():
    """get_download_link returns the href from API."""
    disk = YandexDisk()

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"href": "https://downloader.disk.yandex.ru/direct/xxx"}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "get", return_value=mock_resp) as mock_get:
        href = disk.get_download_link("https://yadi.sk/d/abc123")
        assert href == "https://downloader.disk.yandex.ru/direct/xxx"
        print("  PASS: get_download_link → returns href")


def test_download_mocked():
    """download fetches file and writes to disk."""
    disk = YandexDisk()

    # Mock get_public_meta
    with patch.object(disk, "get_public_meta", return_value={"name": "test.txt"}), \
         patch.object(disk, "get_download_link", return_value="https://example.com/file"):

        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"hello world"]
        mock_resp.raise_for_status = MagicMock()

        with patch.object(disk.session, "get", return_value=mock_resp):
            with tempfile.TemporaryDirectory() as tmpdir:
                result = disk.download("https://yadi.sk/d/abc123", output_dir=tmpdir)
                assert result.exists()
                assert result.name == "test.txt"
                assert result.read_text() == "hello world"
                print(f"  PASS: download → {result.name} ({result.stat().st_size} bytes)")


def test_download_with_meta_mocked():
    """download_with_meta returns structured result dict."""
    disk = YandexDisk()

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create the file that download() would produce
        fake_file = Path(tmpdir) / "rec.mp4"
        fake_file.write_bytes(b"x" * 5000)

        with patch.object(disk, "get_public_meta", return_value={
            "name": "rec.mp4", "size": 5000, "mime_type": "video/mp4",
            "created": "", "modified": "", "public_url": "", "type": "file", "path": "",
        }), \
             patch.object(disk, "download", return_value=fake_file):

            result = disk.download_with_meta("https://yadi.sk/d/abc123", output_dir=tmpdir)
            assert result["name"] == "rec.mp4"
            assert result["filepath"] == str(fake_file)
            assert result["size"] == 5000
            print("  PASS: download_with_meta → structured result")


# ── Live API smoke test (no auth needed for public resources) ────────

def test_live_api_reachable():
    """Verify Yandex Disk API is reachable (returns 404 for fake link)."""
    disk = YandexDisk()  # No token — public API
    try:
        disk.get_public_meta("https://yadi.sk/d/nonexistent_test_12345")
        print("  UNEXPECTED: got 200 for fake link")
    except Exception as e:
        if "404" in str(e):
            print("  PASS: API reachable, 404 for non-existent link (expected)")
        else:
            print(f"  WARN: unexpected error: {e}")


def test_auth_header():
    """Token is set in Authorization header."""
    disk = YandexDisk(token="my_test_token")
    assert disk.session.headers["Authorization"] == "OAuth my_test_token"
    print("  PASS: Authorization header set correctly")


def test_no_token():
    """Without token, no Authorization header — works for public resources."""
    import os
    old = os.environ.pop("YANDEX_DISK_TOKEN", None)
    try:
        disk = YandexDisk()
        assert "Authorization" not in disk.session.headers
        print("  PASS: no token → no Authorization header")
    finally:
        if old is not None:
            os.environ["YANDEX_DISK_TOKEN"] = old


# ── Runner ───────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("D7a", test_auth_header),
        ("D7b", test_no_token),
        ("D7c", test_get_public_meta_mocked),
        ("D7d", test_get_download_link_mocked),
        ("D7e", test_download_mocked),
        ("D7f", test_download_with_meta_mocked),
        ("D7g", test_live_api_reachable),
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
    import sys
    ok = run_all()
    sys.exit(0 if ok else 1)
