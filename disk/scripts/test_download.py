#!/usr/bin/env python3
"""Tests for disk downloader and share management."""

import json
import os
import tempfile
from pathlib import Path
from io import StringIO
from unittest.mock import MagicMock, patch

import requests

from download import YandexDisk, API_BASE
import share
import upload


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


def test_get_public_meta_defaults_to_authenticated_session():
    """Public-link metadata uses OAuth by default when a token exists."""
    disk = YandexDisk(token="test_token")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"name": "video.mp4"}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "get", return_value=mock_resp) as mock_get:
        disk.get_public_meta("https://yadi.sk/d/abc123")
        mock_get.assert_called_once()


def test_get_public_meta_anonymous_uses_fresh_session():
    """Anonymous mode bypasses the authenticated session explicitly."""
    disk = YandexDisk(token="test_token")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"name": "video.mp4"}
    mock_resp.raise_for_status = MagicMock()

    with patch("download.requests.Session") as mock_session_cls:
        temp_session = MagicMock()
        temp_session.get.return_value = mock_resp
        mock_session_cls.return_value = temp_session

        disk.get_public_meta("https://yadi.sk/d/abc123", anonymous=True)

        temp_session.get.assert_called_once_with(
            f"{API_BASE}/v1/disk/public/resources",
            params={"public_key": "https://yadi.sk/d/abc123"},
        )


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


def test_cli_rejects_force_auth_with_anonymous(capsys):
    """CLI rejects contradictory auth flags."""
    argv = [
        "download.py",
        "https://yadi.sk/d/abc123",
        "--force-auth",
        "--anonymous",
    ]
    with patch("sys.argv", argv):
        try:
            from download import main

            main()
        except SystemExit as exc:
            assert exc.code == 2
    captured = capsys.readouterr()
    assert "mutually exclusive" in captured.err


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


def test_get_resource_meta_mocked():
    """get_resource_meta uses authenticated metadata endpoint."""
    disk = YandexDisk(token="write_token")
    mock_resp = MagicMock()
    mock_resp.content = b'{"path":"disk:/team/report.txt"}'
    mock_resp.json.return_value = {"path": "disk:/team/report.txt"}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "request", return_value=mock_resp) as mock_request:
        meta = disk.get_resource_meta("disk:/team/report.txt")
        mock_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/v1/disk/resources",
            params={"path": "disk:/team/report.txt"},
        )
        assert meta["path"] == "disk:/team/report.txt"


def test_publish_file_mocked():
    """publish_file builds payload and normalizes response."""
    disk = YandexDisk(token="write_token")
    mock_resp = MagicMock()
    mock_resp.content = b'{"public_key":"pk","public_url":"https://disk.yandex.ru/d/abc","public_settings":{"accesses":[]}}'
    mock_resp.json.return_value = {
        "public_key": "pk",
        "public_url": "https://disk.yandex.ru/d/abc",
        "public_settings": {"accesses": []},
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "request", return_value=mock_resp) as mock_request, \
         patch.object(disk, "_normalize_available_until", return_value=1234567890):
        result = disk.publish_file(
            path="disk:/team/report.txt",
            access="all",
            rights="read",
            available_until=3600,
            user_ids=["101", "202"],
        )
        mock_request.assert_called_once_with(
            "PUT",
            f"{API_BASE}/v1/disk/resources/publish",
            params={"path": "disk:/team/report.txt", "allow_address_access": "true"},
            json={
                "public_settings": {
                    "available_until": 1234567890,
                    "accesses": [
                        {"macros": ["all"], "rights": ["read"]},
                        {"user_ids": ["101", "202"], "rights": ["read"]},
                    ],
                }
            },
        )
        assert result["public_key"] == "pk"
        assert result["path"] == "disk:/team/report.txt"


def test_publish_file_refreshes_metadata_when_api_returns_href_only():
    """publish_file follows the href-style response with a metadata refresh."""
    disk = YandexDisk(token="write_token")
    mock_resp = MagicMock()
    mock_resp.content = b'{"method":"GET","href":"https://cloud-api.yandex.net/v1/disk/resources?...","templated":false}'
    mock_resp.json.return_value = {
        "method": "GET",
        "href": "https://cloud-api.yandex.net/v1/disk/resources?path=disk:/team/report.txt",
        "templated": False,
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "request", return_value=mock_resp) as mock_request, \
         patch.object(
             disk,
             "get_share_info",
             return_value={
                 "path": "disk:/team/report.txt",
                 "public_key": "pk",
                 "public_url": "https://disk.yandex.ru/d/abc",
                 "public_settings": {},
             },
         ) as mock_info:
        result = disk.publish_file(path="disk:/team/report.txt", access="all", rights="read")
        mock_request.assert_called_once()
        mock_info.assert_called_once_with("disk:/team/report.txt")
        assert result["public_url"] == "https://disk.yandex.ru/d/abc"


def test_build_share_payload_matches_documented_public_settings_shape():
    """employees/org payload matches the documented public_settings schema."""
    disk = YandexDisk(token="write_token")
    with patch("download.time.time", return_value=1_700_000_000):
        payload = disk._build_share_payload(
            access="employees",
            org_id="123456",
            rights="read",
            available_until=3600,
            user_ids=["user-1"],
            group_ids=["55"],
            department_ids=["77"],
        )
    assert payload == {
        "public_settings": {
            "available_until": 1_700_003_600,
            "accesses": [
                {"macros": ["employees"], "org_id": 123456, "rights": ["read"]},
                {"user_ids": ["user-1"], "rights": ["read"]},
                {"group_ids": [55], "rights": ["read"]},
                {"department_ids": [77], "rights": ["read"]},
            ],
        }
    }


def test_normalize_available_until_converts_ttl_seconds():
    """TTL seconds are converted to a future Unix timestamp."""
    disk = YandexDisk(token="write_token")
    with patch("download.time.time", return_value=1_700_000_000):
        assert disk._normalize_available_until(3600) == 1_700_003_600


def test_normalize_available_until_keeps_future_timestamp():
    """Future Unix timestamps remain unchanged for compatibility."""
    disk = YandexDisk(token="write_token")
    with patch("download.time.time", return_value=1_700_000_000):
        assert disk._normalize_available_until(1_700_100_000) == 1_700_100_000


def test_update_share_settings_uses_publish_endpoint():
    """update_share_settings reuses publish endpoint for updates."""
    disk = YandexDisk(token="write_token")
    info = {
        "path": "disk:/team/report.txt",
        "public_key": "pk",
        "public_url": "https://disk.yandex.ru/d/abc",
        "public_settings": {"accesses": [{"access": "all"}]},
    }
    mock_resp = MagicMock()
    mock_resp.content = b'{"public_key":"pk","public_url":"https://disk.yandex.ru/d/abc","public_settings":{"accesses":[{"macros":["employees"],"org_id":123456,"rights":["write"]}]}}'
    mock_resp.json.return_value = {
        "public_key": "pk",
        "public_url": "https://disk.yandex.ru/d/abc",
        "public_settings": {"accesses": [{"macros": ["employees"], "org_id": 123456, "rights": ["write"]}]},
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk, "get_share_info", return_value=info), \
         patch.object(disk.session, "request", return_value=mock_resp) as mock_request:
        result = disk.update_share_settings(
            path="disk:/team/report.txt",
            access="employees",
            org_id="123456",
            rights="write",
        )
        mock_request.assert_called_once()
        assert result["public_settings"]["accesses"][0]["macros"] == ["employees"]


def test_unpublish_file_mocked():
    """unpublish_file issues unpublish request and returns success payload."""
    disk = YandexDisk(token="write_token")
    mock_resp = MagicMock()
    mock_resp.content = b""
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "request", return_value=mock_resp) as mock_request:
        result = disk.unpublish_file("disk:/team/report.txt")
        mock_request.assert_called_once_with(
            "PUT",
            f"{API_BASE}/v1/disk/resources/unpublish",
            params={"path": "disk:/team/report.txt"},
        )
        assert result == {"path": "disk:/team/report.txt", "unpublished": True}


def test_get_share_info_parses_meta():
    """get_share_info returns normalized share metadata."""
    disk = YandexDisk(token="write_token")
    with patch.object(disk, "get_resource_meta", return_value={
        "path": "disk:/team/report.txt",
        "public_key": "pk",
        "public_url": "https://disk.yandex.ru/d/abc",
        "public_settings": {"accesses": [{"access": "all", "rights": "read"}]},
    }):
        result = disk.get_share_info("disk:/team/report.txt")
        assert result["public_url"] == "https://disk.yandex.ru/d/abc"
        assert result["public_settings"]["accesses"][0]["rights"] == "read"


def test_get_share_info_does_not_invent_accesses():
    """get_share_info leaves ACLs absent when metadata does not echo them back."""
    disk = YandexDisk(token="write_token")
    with patch.object(disk, "get_resource_meta", return_value={
        "path": "disk:/team/report.txt",
        "public_key": "pk",
        "public_url": "https://disk.yandex.ru/d/abc",
        "public_settings": {},
        "accesses": [],
    }):
        result = disk.get_share_info("disk:/team/report.txt")
        assert result["public_settings"] == {}


def test_employees_access_requires_org_id():
    """employees access requires org_id from args or token metadata."""
    disk = YandexDisk(token="write_token")
    try:
        disk.publish_file(path="disk:/team/report.txt", access="employees", rights="read")
    except ValueError as exc:
        assert "org_id" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing org_id")


def test_employees_access_uses_org_id_from_explicit_token_file(tmp_path):
    """employees access resolves org_id from the explicit token file when provided."""
    token_path = tmp_path / "corp.token"
    token_path.write_text(
        json.dumps({"email": "user@example.com", "token.disk": "write_token", "org_id": "123456"}),
        encoding="utf-8",
    )
    disk = YandexDisk(token_file=str(token_path), account="corp")
    payload = disk._build_share_payload(access="employees", rights="read")
    assert payload["public_settings"]["accesses"][0]["org_id"] == 123456


def test_password_requires_password_rights():
    """password cannot be used with plain read/write rights."""
    disk = YandexDisk(token="write_token")
    try:
        disk.publish_file(
            path="disk:/team/report.txt",
            access="all",
            rights="read",
            password="secret",
        )
    except ValueError as exc:
        assert "password" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid password/rights combination")


def test_share_requires_token():
    """share-management methods fail fast without OAuth token."""
    disk = YandexDisk(token=None)
    try:
        disk.get_share_info("disk:/team/report.txt")
    except RuntimeError as exc:
        assert "Disk authentication is required" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when token is missing")


def test_share_cli_parses_and_prints_json():
    """share CLI parses CSV ids and prints JSON output."""
    parser = share.build_parser()
    args = parser.parse_args([
        "publish",
        "--account", "alex",
        "--path", "disk:/team/report.txt",
        "--access", "all",
        "--rights", "read",
        "--user-ids", "1,2",
    ])

    fake_stdout = StringIO()
    with patch("share.YandexDisk") as mock_disk_cls, \
         patch("sys.stdout", fake_stdout):
        mock_disk = mock_disk_cls.return_value
        mock_disk.publish_file.return_value = {"path": "disk:/team/report.txt", "public_key": "pk", "public_url": "url", "public_settings": {}}
        with patch.object(share, "build_parser", return_value=parser), \
             patch("sys.argv", ["share.py", "publish", "--account", "alex", "--path", "disk:/team/report.txt", "--access", "all", "--rights", "read", "--user-ids", "1,2"]):
            code = share.main()
        assert code == 0
        mock_disk.publish_file.assert_called_once_with(
            path="disk:/team/report.txt",
            access="all",
            org_id=None,
            rights="read",
            password=None,
            available_until=None,
            user_ids=["1", "2"],
            group_ids=None,
            department_ids=None,
        )
        assert '"public_key": "pk"' in fake_stdout.getvalue()


def test_share_cli_returns_nonzero_on_validation_error():
    """share CLI returns non-zero and prints JSON error payload."""
    parser = share.build_parser()
    fake_stderr = StringIO()
    with patch("share.YandexDisk") as mock_disk_cls, \
         patch("sys.stderr", fake_stderr), \
         patch.object(share, "build_parser", return_value=parser), \
         patch("sys.argv", ["share.py", "info", "--account", "alex", "--path", "disk:/team/report.txt"]):
        mock_disk = mock_disk_cls.return_value
        mock_disk.get_share_info.side_effect = RuntimeError("boom")
        code = share.main()
        assert code == 1
        assert '"error": "boom"' in fake_stderr.getvalue()


def test_ensure_dir_is_idempotent():
    """ensure_dir treats 409 as already exists."""
    disk = YandexDisk(token="write_token")
    mock_resp = MagicMock()
    mock_resp.status_code = 409
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "request", return_value=mock_resp) as mock_request:
        result = disk.ensure_dir("disk:/Проекты")
        mock_request.assert_called_once_with(
            "PUT",
            f"{API_BASE}/v1/disk/resources",
            params={"path": "disk:/Проекты"},
        )
        assert result == {"path": "disk:/Проекты", "created": False}


def test_get_upload_link_mocked():
    """get_upload_link requests upload target with overwrite flag."""
    disk = YandexDisk(token="write_token")
    mock_resp = MagicMock()
    mock_resp.content = b'{"href":"https://uploader.disk.yandex.net/abc"}'
    mock_resp.json.return_value = {"href": "https://uploader.disk.yandex.net/abc"}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "request", return_value=mock_resp) as mock_request:
        result = disk.get_upload_link("disk:/Проекты/photo.jpg", overwrite=True)
        mock_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/v1/disk/resources/upload",
            params={"path": "disk:/Проекты/photo.jpg", "overwrite": "true"},
        )
        assert result["href"] == "https://uploader.disk.yandex.net/abc"


def test_upload_file_creates_parents_and_fetches_meta():
    """upload_file creates parents, uploads bytes, and returns normalized metadata."""
    disk = YandexDisk(token="write_token")

    upload_link_resp = MagicMock()
    upload_link_resp.content = b'{"href":"https://uploader.disk.yandex.net/abc"}'
    upload_link_resp.json.return_value = {"href": "https://uploader.disk.yandex.net/abc"}
    upload_link_resp.raise_for_status = MagicMock()

    upload_resp = MagicMock()
    upload_resp.raise_for_status = MagicMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        local_file = Path(tmpdir) / "photo.jpg"
        local_file.write_bytes(b"image-bytes")

        with patch.object(disk, "ensure_parent_dirs", return_value=[{"path": "disk:/Проекты", "created": True}]) as mock_parents, \
             patch.object(disk.session, "request", side_effect=[upload_link_resp, upload_resp]) as mock_request, \
             patch.object(disk, "get_resource_meta", return_value={"path": "disk:/Проекты/photo.jpg", "name": "photo.jpg", "size": 11, "mime_type": "image/jpeg"}):
            result = disk.upload_file(local_file, "disk:/Проекты/photo.jpg")

        mock_parents.assert_called_once_with("disk:/Проекты/photo.jpg")
        assert mock_request.call_args_list[0].kwargs["params"] == {
            "path": "disk:/Проекты/photo.jpg",
            "overwrite": "false",
        }
        assert mock_request.call_args_list[1].args[:2] == ("PUT", "https://uploader.disk.yandex.net/abc")
        assert result["remote_path"] == "disk:/Проекты/photo.jpg"
        assert result["name"] == "photo.jpg"
        assert result["uploaded"] is True
        assert result["created_dirs"] == [{"path": "disk:/Проекты", "created": True}]


def test_upload_and_publish_combines_results():
    """upload_and_publish merges upload metadata with share response."""
    disk = YandexDisk(token="write_token")
    with patch.object(disk, "upload_file", return_value={"remote_path": "disk:/Docs/report.pdf", "uploaded": True}), \
         patch.object(disk, "publish_file", return_value={"public_key": "pk", "public_url": "url", "public_settings": {"accesses": []}}):
        result = disk.upload_and_publish(
            "report.pdf",
            "disk:/Docs/report.pdf",
            access="all",
            rights="read",
        )
        assert result["uploaded"] is True
        assert result["public_key"] == "pk"
        assert result["public_url"] == "url"


def test_upload_requires_local_file():
    """upload_file fails fast when local file is missing."""
    disk = YandexDisk(token="write_token")
    try:
        disk.upload_file("/tmp/definitely-missing-file.txt", "disk:/Docs/missing.txt")
    except ValueError as exc:
        assert "Local file not found" in str(exc)
    else:
        raise AssertionError("Expected ValueError when local file is missing")


def test_upload_cli_parses_publish_and_prints_json():
    """upload CLI forwards publish options and prints JSON output."""
    parser = upload.build_parser()
    fake_stdout = StringIO()
    argv = [
        "upload.py",
        "--account", "alex",
        "--local", "./photo.jpg",
        "--remote", "disk:/Проекты/photo.jpg",
        "--publish",
        "--access", "all",
        "--rights", "read",
        "--user-ids", "1,2",
    ]

    with patch("upload.YandexDisk") as mock_disk_cls, \
         patch("sys.stdout", fake_stdout), \
         patch.object(upload, "build_parser", return_value=parser), \
         patch("sys.argv", argv):
        mock_disk = mock_disk_cls.return_value
        mock_disk.upload_and_publish.return_value = {"remote_path": "disk:/Проекты/photo.jpg", "public_url": "url"}
        code = upload.main()
        assert code == 0
        mock_disk.upload_and_publish.assert_called_once_with(
            "./photo.jpg",
            "disk:/Проекты/photo.jpg",
            overwrite=False,
            create_parents=True,
            access="all",
            org_id=None,
            rights="read",
            password=None,
            available_until=None,
            user_ids=["1", "2"],
            group_ids=None,
            department_ids=None,
        )
        assert '"public_url": "url"' in fake_stdout.getvalue()


def test_upload_cli_returns_nonzero_on_error():
    """upload CLI returns non-zero and prints JSON error payload."""
    parser = upload.build_parser()
    fake_stderr = StringIO()
    argv = [
        "upload.py",
        "--account", "alex",
        "--local", "./photo.jpg",
        "--remote", "disk:/Проекты/photo.jpg",
    ]

    with patch("upload.YandexDisk") as mock_disk_cls, \
         patch("sys.stderr", fake_stderr), \
         patch.object(upload, "build_parser", return_value=parser), \
         patch("sys.argv", argv):
        mock_disk = mock_disk_cls.return_value
        mock_disk.upload_file.side_effect = RuntimeError("boom")
        code = upload.main()
        assert code == 1
        assert '"error": "boom"' in fake_stderr.getvalue()


def test_live_restricted_publish_requires_auth_when_enabled():
    """Optional live test: employees-only publish must reject anonymous public-resource access."""
    token_file = os.getenv("YANDEX_DISK_LIVE_TOKEN_FILE")
    org_id = os.getenv("YANDEX_DISK_LIVE_ORG_ID")
    base_path = os.getenv("YANDEX_DISK_LIVE_BASE_PATH")
    if not token_file or not org_id or not base_path:
        return

    disk = YandexDisk(
        token_file=token_file,
        required_scopes=["cloud_api:disk.read", "cloud_api:disk.write", "cloud_api:disk.app_folder"],
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        local_file = Path(tmpdir) / "live-restricted.txt"
        local_file.write_text("live restricted\n", encoding="utf-8")
        remote = f"{base_path}/live-restricted.txt"
        result = disk.upload_and_publish(
            str(local_file),
            remote,
            overwrite=True,
            access="employees",
            org_id=org_id,
            rights="read",
        )
        public_url = result["public_url"]
        assert public_url
        assert requests.get(
            f"{disk.api_base}/v1/disk/public/resources",
            params={"public_key": public_url},
            timeout=20,
        ).status_code == 404
        auth_meta = disk.get_public_meta(public_url)
        assert auth_meta["name"] == "live-restricted.txt"


def test_live_public_publish_verified_when_enabled():
    """Optional live test: public publish returns a public URL reachable via public metadata API."""
    token_file = os.getenv("YANDEX_DISK_LIVE_TOKEN_FILE")
    base_path = os.getenv("YANDEX_DISK_LIVE_BASE_PATH")
    if not token_file or not base_path:
        return

    disk = YandexDisk(
        token_file=token_file,
        required_scopes=["cloud_api:disk.read", "cloud_api:disk.write", "cloud_api:disk.app_folder"],
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        local_file = Path(tmpdir) / "live-public.txt"
        local_file.write_text("live public\n", encoding="utf-8")
        remote = f"{base_path}/live-public.txt"
        result = disk.upload_and_publish(
            str(local_file),
            remote,
            overwrite=True,
            access="all",
            rights="read",
        )
        assert result.get("public_url")
        resp = requests.get(
            f"{disk.api_base}/v1/disk/public/resources",
            params={"public_key": result["public_url"]},
            timeout=20,
        )
        assert resp.status_code == 200, resp.text
        disk.unpublish_file(remote)


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
        ("D7h", test_get_resource_meta_mocked),
        ("D7i", test_publish_file_mocked),
        ("D7j", test_publish_file_refreshes_metadata_when_api_returns_href_only),
        ("D7k", test_restricted_publish_revokes_public_link_when_verification_fails),
        ("D7l", test_update_share_settings_uses_publish_endpoint),
        ("D7m", test_unpublish_file_mocked),
        ("D7n", test_get_share_info_parses_meta),
        ("D7o", test_employees_access_requires_org_id),
        ("D7p", test_password_requires_password_rights),
        ("D7q", test_share_requires_token),
        ("D7r", test_share_cli_parses_and_prints_json),
        ("D7s", test_share_cli_returns_nonzero_on_validation_error),
        ("D7t", test_ensure_dir_is_idempotent),
        ("D7u", test_get_upload_link_mocked),
        ("D7v", test_upload_file_creates_parents_and_fetches_meta),
        ("D7w", test_upload_and_publish_combines_results),
        ("D7x", test_upload_requires_local_file),
        ("D7y", test_upload_cli_parses_publish_and_prints_json),
        ("D7z", test_upload_cli_returns_nonzero_on_error),
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
