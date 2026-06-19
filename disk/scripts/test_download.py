#!/usr/bin/env python3
"""Tests for disk downloader and share management."""

import ast
import json
import os
import sys
import tempfile
from pathlib import Path
from io import StringIO
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from disk.scripts import disk as disk_script
from disk.scripts import download, import_url, list as list_script, s3_upload, share, upload
from disk.lib.api import API_BASE
from disk.lib.workflows import YandexDisk


def test_disk_library_symbols_have_design_docstrings():
    """New Disk library layers must preserve source-level design context."""

    library_paths = [
        Path(__file__).resolve().parents[1] / "lib" / "api.py",
        Path(__file__).resolve().parents[1] / "lib" / "client.py",
        Path(__file__).resolve().parents[1] / "lib" / "cli.py",
        Path(__file__).resolve().parents[1] / "lib" / "s3.py",
        Path(__file__).resolve().parents[1] / "lib" / "workflows.py",
    ]
    missing: list[str] = []
    for path in library_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if ast.get_docstring(node) is None:
                    missing.append(f"{path.relative_to(Path(__file__).resolve().parents[2])}:{node.lineno} {node.name}")
    assert missing == []


def test_canonical_disk_facade_exposes_all_scenario_subcommands():
    """disk.py is the canonical command surface over scenario adapters."""

    parser = disk_script.build_parser()
    subparsers = next(
        action for action in parser._actions
        if getattr(action, "dest", None) == "command"
    )
    assert set(subparsers.choices) == {
        "download",
        "list",
        "upload",
        "import-url",
        "share",
        "manage",
        "s3-upload",
    }


def disk_with_account(
    tmp_path: Path,
    *,
    account: str = "acct",
    token: str = "write-token",
    client_id: str = "disk-client",
    scopes: list[str] | None = None,
) -> tuple[YandexDisk, Path]:
    """Create a Disk client backed by a real token-file entry."""

    token_path = tmp_path / "auth" / f"{account}.token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(
        json.dumps(
            {
                "email": f"{account}@example.com",
                token: {"client_id": client_id},
            }
        ),
        encoding="utf-8",
    )
    disk = YandexDisk(account=account, data_dir=str(tmp_path))
    disk._config["oauth_apps"] = {
        "catalog": {
            "disk": {
                "client_id": client_id,
                "scopes": scopes
                or [
                    "cloud_api:disk.read",
                    "cloud_api:disk.write",
                    "cloud_api:disk.app_folder",
                ],
            }
        }
    }
    return disk, token_path


# ── Unit tests (mocked HTTP) ────────────────────────────────────────

def test_get_public_meta_mocked():
    """get_public_meta builds correct request and parses response."""
    disk = YandexDisk()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"name":"video.mp4"}'
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

    with patch.object(disk.session, "request", return_value=mock_resp) as mock_request:
        meta = disk.get_public_meta("https://yadi.sk/d/abc123")

        mock_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/v1/disk/public/resources",
            headers={},
            params={"public_key": "https://yadi.sk/d/abc123"},
        )
        assert meta["name"] == "video.mp4"
        assert meta["size"] == 1234567
        assert meta["mime_type"] == "video/mp4"
        print("  PASS: get_public_meta → correct request + parsing")


def test_get_public_meta_bypasses_token_resolution(tmp_path):
    """Public-link metadata bypasses token-file resolution."""
    disk, _ = disk_with_account(tmp_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"name":"video.mp4"}'
    mock_resp.json.return_value = {"name": "video.mp4"}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "request", return_value=mock_resp) as mock_request:
        disk.get_public_meta("https://yadi.sk/d/abc123")
        assert mock_request.call_args.kwargs["headers"] == {}


def test_get_public_meta_anonymous_is_still_tokenless():
    """The legacy anonymous flag remains a tokenless public call."""
    disk = YandexDisk()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"name":"video.mp4"}'
    mock_resp.json.return_value = {"name": "video.mp4"}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "request", return_value=mock_resp) as mock_request:
        disk.get_public_meta("https://yadi.sk/d/abc123", anonymous=True)

        mock_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/v1/disk/public/resources",
            headers={},
            params={"public_key": "https://yadi.sk/d/abc123"},
        )


def test_get_download_link_mocked():
    """get_download_link returns the href from API."""
    disk = YandexDisk()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"href":"https://downloader.disk.yandex.ru/direct/xxx"}'
    mock_resp.json.return_value = {"href": "https://downloader.disk.yandex.ru/direct/xxx"}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "request", return_value=mock_resp):
        href = disk.get_download_link("https://yadi.sk/d/abc123")
        assert href == "https://downloader.disk.yandex.ru/direct/xxx"
        print("  PASS: get_download_link → returns href")


def test_cli_rejects_token_file_option(capsys):
    """Disk CLI no longer accepts direct token-file auth."""
    argv = [
        "download.py",
        "https://yadi.sk/d/abc123",
        "--token-file",
        "/tmp/acct.token",
    ]
    with patch("sys.argv", argv):
        try:
            from disk.scripts.download import main

            main()
        except SystemExit as exc:
            assert exc.code == 2
    captured = capsys.readouterr()
    assert "--token-file" in captured.err


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


def test_constructor_does_not_accept_raw_token():
    """Raw Disk tokens are not a supported constructor auth path."""
    try:
        YandexDisk(token="my_test_token")
    except TypeError:
        pass
    else:
        raise AssertionError("Expected raw token constructor argument to be rejected")


def test_env_token_is_ignored(monkeypatch):
    """Legacy env auth is not attached as a raw Disk fallback."""
    monkeypatch.setenv("YANDEX_DISK_TOKEN", "raw-token")
    disk = YandexDisk()
    assert "Authorization" not in disk.session.headers
    print("  PASS: env token ignored")


def test_disk_client_has_no_task_local_legacy_env_digest():
    """Disk runtime does not expose a task-local env-token import hook."""

    assert not hasattr(YandexDisk(account="acct"), "digest_legacy_disk_token_env")


def test_get_resource_meta_mocked(tmp_path):
    """get_resource_meta uses authenticated metadata endpoint."""
    disk, _ = disk_with_account(tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"path":"disk:/team/report.txt"}'
    mock_resp.json.return_value = {"path": "disk:/team/report.txt"}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "request", return_value=mock_resp) as mock_request:
        meta = disk.get_resource_meta("disk:/team/report.txt")
        mock_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/v1/disk/resources",
            headers={"Authorization": "OAuth write-token"},
            params={"path": "disk:/team/report.txt"},
        )
        assert meta["path"] == "disk:/team/report.txt"


def test_get_resource_meta_uses_account_token_dispatch(tmp_path):
    """Account-backed Disk calls use decorator scopes and persist token health."""
    token_path = tmp_path / "auth" / "acct.token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text(
        json.dumps(
            {
                "email": "acct@example.com",
                "read-token": {"client_id": "disk-read-client"},
            }
        ),
        encoding="utf-8",
    )
    disk = YandexDisk(account="acct", data_dir=str(tmp_path))
    disk._config["oauth_apps"] = {
        "catalog": {
            "disk-read": {
                "client_id": "disk-read-client",
                "scopes": ["cloud_api:disk.read"],
            }
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"path":"disk:/team/report.txt"}'
    mock_resp.json.return_value = {"path": "disk:/team/report.txt"}

    with patch.object(disk.session, "request", return_value=mock_resp) as mock_request:
        meta = disk.get_resource_meta("disk:/team/report.txt")

    mock_request.assert_called_once_with(
        "GET",
        f"{API_BASE}/v1/disk/resources",
        headers={"Authorization": "OAuth read-token"},
        params={"path": "disk:/team/report.txt"},
    )
    saved = json.loads(token_path.read_text(encoding="utf-8"))
    assert meta["path"] == "disk:/team/report.txt"
    assert saved["read-token"]["good_at"]
    assert "bad_at" not in saved["read-token"]


def test_list_resource_passes_paging_and_app_scope(tmp_path):
    """Authenticated listing keeps disk:/ and app:/ dispatch separate."""
    disk, _ = disk_with_account(tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"path":"app:/team","_embedded":{"items":[]}}'
    mock_resp.json.return_value = {"path": "app:/team", "_embedded": {"items": []}}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "request", return_value=mock_resp) as mock_request:
        meta = disk.list_resource("app:/team", limit=25, offset=50)

    mock_request.assert_called_once_with(
        "GET",
        f"{API_BASE}/v1/disk/resources",
        headers={"Authorization": "OAuth write-token"},
        params={"path": "app:/team", "limit": 25, "offset": 50},
    )
    assert meta["path"] == "app:/team"


def test_list_script_prints_jsonl_with_data_dir():
    """The list adapter delegates account/data-dir and JSONL output to the CLI facade."""
    parser = list_script.build_parser()
    fake_stdout = StringIO()
    argv = [
        "list.py",
        "--account", "alex",
        "--data-dir", "/tmp/yandex-data",
        "--path", "disk:/Docs",
        "--jsonl",
    ]

    with patch("disk.lib.cli.YandexDisk") as mock_disk_cls, \
         patch("sys.stdout", fake_stdout), \
         patch("disk.lib.cli.build_list_parser", return_value=parser):
        mock_disk = mock_disk_cls.return_value
        mock_disk.list_resource.return_value = {
            "_embedded": {
                "items": [
                    {"name": "one.txt", "path": "disk:/Docs/one.txt", "type": "file", "size": 3}
                ]
            }
        }
        code = list_script.main(argv[1:])

    assert code == 0
    mock_disk_cls.assert_called_once_with(account="alex", data_dir="/tmp/yandex-data")
    assert json.loads(fake_stdout.getvalue())["path"] == "disk:/Docs/one.txt"


def test_private_selected_materialization_preserves_manifest_relative_paths(tmp_path):
    """Selected private downloads materialize only manifest members under the source root."""
    disk = YandexDisk()
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        '{"path":"disk:/Root/a.txt"}\n{"path":"disk:/Root/nested/b.txt"}\n',
        encoding="utf-8",
    )
    output = tmp_path / "out"

    def write_href(_href: str, filepath: Path) -> Path:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(filepath.name, encoding="utf-8")
        return filepath

    with patch.object(disk, "get_resource_meta", return_value={"type": "file", "size": 1}), \
         patch.object(disk, "get_private_download_link", return_value="https://download.example/file"), \
         patch.object(disk, "_download_href_to_file", side_effect=write_href):
        result = disk.materialize_selected_private(
            manifest_path=manifest,
            source_root="disk:/Root",
            output_dir=str(output),
        )

    assert result["surface"] == "disk:/"
    assert (output / "a.txt").read_text(encoding="utf-8") == "a.txt"
    assert (output / "nested" / "b.txt").read_text(encoding="utf-8") == "b.txt"


def test_selected_materialization_rejects_manifest_escape(tmp_path):
    """Manifest entries outside the declared root are rejected before download."""
    disk = YandexDisk()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"path": "disk:/Other/a.txt"}]), encoding="utf-8")

    try:
        disk.materialize_selected_private(
            manifest_path=manifest,
            source_root="disk:/Root",
            output_dir=str(tmp_path / "out"),
        )
    except ValueError as exc:
        assert "outside source root" in str(exc)
    else:
        raise AssertionError("Expected manifest escape to be rejected")


def test_public_folder_materialization_root_and_flatten_modes(tmp_path):
    """--materialize-dir preserves the root; --flatten-single-root omits only that wrapper."""
    disk = YandexDisk()

    def meta(_url: str, anonymous: bool = False, path: str = "", limit=None, offset=None):
        if path == "/nested":
            return {
                "name": "nested",
                "type": "dir",
                "_embedded": {
                    "total": 1,
                    "items": [
                        {"name": "b.txt", "type": "file", "path": "/nested/b.txt", "size": 1}
                    ],
                },
            }
        return {
            "name": "Shared",
            "type": "dir",
            "_embedded": {
                "total": 2,
                "items": [
                    {"name": "a.txt", "type": "file", "path": "/a.txt", "size": 1},
                    {"name": "nested", "type": "dir", "path": "/nested"},
                ],
            },
        }

    def write_href(_href: str, filepath: Path) -> Path:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(filepath.name, encoding="utf-8")
        return filepath

    with patch.object(disk, "get_public_meta", side_effect=meta), \
         patch.object(disk, "get_download_link", return_value="https://download.example/file"), \
         patch.object(disk, "_download_href_to_file", side_effect=write_href):
        root_result = disk.materialize_public_folder("https://disk.yandex.ru/d/folder", output_dir=str(tmp_path / "root"))
        flat_result = disk.materialize_public_folder(
            "https://disk.yandex.ru/d/folder",
            output_dir=str(tmp_path / "flat"),
            flatten_single_root=True,
        )

    assert Path(root_result["output_root"]).name == "Shared"
    assert (tmp_path / "root" / "Shared" / "nested" / "b.txt").exists()
    assert Path(flat_result["output_root"]) == (tmp_path / "flat").resolve()
    assert (tmp_path / "flat" / "nested" / "b.txt").exists()
    assert not (tmp_path / "flat" / "Shared").exists()


def test_public_file_tolerates_folder_flags(tmp_path):
    """Folder-mode flags on a public file download are accepted and reported as not applied."""
    disk = YandexDisk()
    fake_file = tmp_path / "file.txt"
    fake_file.write_text("x", encoding="utf-8")
    with patch.object(disk, "get_public_meta", return_value={
        "name": "file.txt",
        "size": 1,
        "mime_type": "text/plain",
        "type": "file",
    }), \
         patch.object(disk, "download", return_value=fake_file):
        result = disk.download_with_meta(
            "https://disk.yandex.ru/d/file",
            output_dir=str(tmp_path),
            materialize_dir=True,
            flatten_single_root=True,
        )
    assert result["resource_type"] == "file"
    assert result["folder_mode_applied"] is False
    assert result["requested_flatten_single_root"] is True


def test_upload_from_url_redacts_result_and_uses_disk_write(tmp_path):
    """Upload-from-URL sends the source URL but only reports its host."""
    disk, _ = disk_with_account(tmp_path)
    source = "https://files.example.test/download?sig=secret"
    mock_resp = MagicMock()
    mock_resp.status_code = 202
    mock_resp.content = b'{"href":"https://cloud-api.yandex.net/v1/disk/operations/op-123"}'
    mock_resp.json.return_value = {"href": "https://cloud-api.yandex.net/v1/disk/operations/op-123"}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "request", return_value=mock_resp) as mock_request:
        result = disk.upload_from_url(
            source_url=source,
            remote_path="disk:/Imports/file.txt",
            overwrite=True,
            disable_redirects=True,
        )

    mock_request.assert_called_once_with(
        "POST",
        f"{API_BASE}/v1/disk/resources/upload",
        headers={"Authorization": "OAuth write-token"},
        params={
            "path": "disk:/Imports/file.txt",
            "url": source,
            "overwrite": "true",
            "disable_redirects": "true",
        },
    )
    encoded = json.dumps(result)
    assert "files.example.test" in encoded
    assert "sig=secret" not in encoded
    assert result["operation_id"] == "op-123"


def test_copy_move_delete_dispatch_by_surface(tmp_path):
    """CRUD helpers preserve disk:/ and app:/ as distinct auth surfaces."""
    disk, _ = disk_with_account(tmp_path)
    op_resp = MagicMock()
    op_resp.status_code = 202
    op_resp.content = b'{"href":"https://cloud-api.yandex.net/v1/disk/operations/op-1"}'
    op_resp.json.return_value = {"href": "https://cloud-api.yandex.net/v1/disk/operations/op-1"}
    op_resp.raise_for_status = MagicMock()
    delete_resp = MagicMock()
    delete_resp.status_code = 204
    delete_resp.content = b""
    delete_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "request", side_effect=[op_resp, delete_resp]) as mock_request:
        copied = disk.copy_resource("disk:/Docs/a.txt", "disk:/Docs/b.txt", overwrite=True)
        deleted = disk.delete_resource("app:/Docs/b.txt", permanently=True)

    assert copied["surface"] == "disk:/"
    assert deleted["surface"] == "app:/"
    assert mock_request.call_args_list[0].kwargs["params"] == {
        "from": "disk:/Docs/a.txt",
        "path": "disk:/Docs/b.txt",
        "overwrite": "true",
    }
    assert mock_request.call_args_list[1].kwargs["params"] == {
        "path": "app:/Docs/b.txt",
        "permanently": "true",
        "force_async": "false",
    }


def test_import_url_cli_redacts_source_url_on_error():
    """The import-url adapter never emits the full source URL in error JSON."""
    parser = import_url.build_parser()
    fake_stderr = StringIO()
    source = "https://files.example.test/object?signature=secret"
    argv = [
        "import_url.py",
        "--account", "alex",
        "--source-url", source,
        "--remote", "disk:/Imports/file.bin",
    ]
    with patch("disk.lib.cli.YandexDisk") as mock_disk_cls, \
         patch("sys.stderr", fake_stderr), \
         patch("disk.lib.cli.build_import_url_parser", return_value=parser):
        mock_disk = mock_disk_cls.return_value
        mock_disk.upload_from_url.side_effect = RuntimeError(f"failed {source}")
        code = import_url.main(argv[1:])
    assert code == 1
    assert source not in fake_stderr.getvalue()
    assert "<redacted-url>" in fake_stderr.getvalue()


def test_s3_config_uses_disk_schema_without_env_file_parser(tmp_path):
    """S3 helper resolves non-secret settings from disk.s3 and CLI options."""

    assert not hasattr(s3_upload, "load_env_file")
    assert s3_upload.object_key("prefix/", None, Path("/tmp/file.bin")) == "prefix/file.bin"
    default_args = s3_upload.build_parser().parse_args([
        "--local", "/tmp/file.bin",
        "--remote", "disk:/file.bin",
        "--data-dir", str(tmp_path),
    ])
    default_config = s3_upload.resolve_s3_config(default_args)
    assert default_config.bucket == "yandex-office"

    args = s3_upload.build_parser().parse_args([
        "--local", "/tmp/file.bin",
        "--remote", "disk:/file.bin",
        "--data-dir", str(tmp_path),
        "--s3-bucket", "velizar-gitea-backup",
        "--multipart-threshold-mib", "16",
        "--multipart-chunk-mib", "8",
        "--max-concurrency", "2",
    ])
    config = s3_upload.resolve_s3_config(args)
    assert config.bucket == "velizar-gitea-backup"
    assert config.endpoint_url == "https://storage.yandexcloud.net"
    assert args.multipart_threshold_mib == 16
    assert args.multipart_chunk_mib == 8
    assert args.max_concurrency == 2

    with patch("sys.stderr", new_callable=StringIO):
        try:
            s3_upload.build_parser().parse_args(["--env-file", "legacy.env"])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("--env-file must not be accepted")


def test_s3_upload_creates_parent_dirs_before_import_and_cleans(tmp_path):
    """S3 helper mirrors direct upload by preparing Disk parents before import."""

    local_file = tmp_path / "file.bin"
    local_file.write_bytes(b"data")
    fake_config = s3_upload.S3BridgeConfig(
        endpoint_url="https://storage.yandexcloud.net",
        region="ru-central1",
        bucket="bucket",
        prefix="prefix",
        presign_ttl_seconds=7200,
        cleanup_after_disk_import=True,
        multipart_threshold_mib=64,
        multipart_chunk_mib=64,
        max_concurrency=None,
    )
    fake_stdout = StringIO()
    remote = "app:/OpenClaw-test/file.bin"
    signed_url = "https://storage.yandexcloud.net/bucket/key?signature=secret"

    with patch("disk.lib.s3.resolve_s3_config", return_value=fake_config), \
         patch("disk.lib.s3.create_s3_client", return_value=object()) as mock_client, \
         patch("disk.lib.s3.upload_to_s3") as mock_upload_to_s3, \
         patch("disk.lib.s3.presign_get", return_value=signed_url), \
         patch(
             "disk.lib.s3.cleanup_objects",
             return_value={"attempted": True, "deleted": ["prefix/file.bin"], "errors": []},
         ) as mock_cleanup, \
         patch("disk.lib.s3.YandexDisk") as mock_disk_cls, \
         patch("sys.stdout", fake_stdout):
        mock_disk = mock_disk_cls.return_value
        mock_disk.ensure_parent_dirs.return_value = [
            {"path": "app:/OpenClaw-test", "created": True}
        ]
        mock_disk.upload_from_url.return_value = {
            "surface": "app:/",
            "path": remote,
            "operation_status": "success",
            "size": 4,
            "imported": True,
        }
        code = s3_upload.main([
            "--account", "alex",
            "--data-dir", str(tmp_path),
            "--local", str(local_file),
            "--remote", remote,
            "--overwrite",
        ])

    assert code == 0
    mock_client.assert_called_once_with(fake_config)
    mock_upload_to_s3.assert_called_once()
    mock_disk.ensure_parent_dirs.assert_called_once_with(remote)
    mock_disk.upload_from_url.assert_called_once_with(
        source_url=signed_url,
        remote_path=remote,
        overwrite=True,
        wait=True,
        timeout_seconds=1800,
        poll_seconds=3,
        verify_size=4,
    )
    mock_cleanup.assert_called_once()
    payload = json.loads(fake_stdout.getvalue())
    assert payload["ok"] is True
    assert payload["created_dirs"] == [{"path": "app:/OpenClaw-test", "created": True}]
    assert payload["s3"]["presigned_urls"] == "redacted"


def test_publish_file_mocked(tmp_path):
    """publish_file builds payload and normalizes response."""
    disk, _ = disk_with_account(tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
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
            headers={"Authorization": "OAuth write-token"},
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


def test_publish_file_refreshes_metadata_when_api_returns_href_only(tmp_path):
    """publish_file follows the href-style response with a metadata refresh."""
    disk, _ = disk_with_account(tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
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
    disk = YandexDisk()
    with patch("disk.lib.workflows.time.time", return_value=1_700_000_000):
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
    disk = YandexDisk()
    with patch("disk.lib.workflows.time.time", return_value=1_700_000_000):
        assert disk._normalize_available_until(3600) == 1_700_003_600


def test_normalize_available_until_keeps_future_timestamp():
    """Future Unix timestamps remain unchanged for compatibility."""
    disk = YandexDisk()
    with patch("disk.lib.workflows.time.time", return_value=1_700_000_000):
        assert disk._normalize_available_until(1_700_100_000) == 1_700_100_000


def test_update_share_settings_uses_publish_endpoint(tmp_path):
    """update_share_settings reuses publish endpoint for updates."""
    disk, _ = disk_with_account(tmp_path)
    info = {
        "path": "disk:/team/report.txt",
        "public_key": "pk",
        "public_url": "https://disk.yandex.ru/d/abc",
        "public_settings": {"accesses": [{"access": "all"}]},
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
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


def test_unpublish_file_mocked(tmp_path):
    """unpublish_file issues unpublish request and returns success payload."""
    disk, _ = disk_with_account(tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b""
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "request", return_value=mock_resp) as mock_request:
        result = disk.unpublish_file("disk:/team/report.txt")
        mock_request.assert_called_once_with(
            "PUT",
            f"{API_BASE}/v1/disk/resources/unpublish",
            headers={"Authorization": "OAuth write-token"},
            params={"path": "disk:/team/report.txt"},
        )
        assert result == {"path": "disk:/team/report.txt", "unpublished": True}


def test_get_share_info_parses_meta():
    """get_share_info returns normalized share metadata."""
    disk = YandexDisk()
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
    disk = YandexDisk()
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
    """employees access requires an explicit org_id."""
    disk = YandexDisk()
    try:
        disk.publish_file(path="disk:/team/report.txt", access="employees", rights="read")
    except ValueError as exc:
        assert "org_id" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing org_id")


def test_employees_access_does_not_read_org_id_from_token_file(tmp_path):
    """Disk share payloads do not read token files for org_id fallback."""
    token_path = tmp_path / "auth" / "corp.token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(
        json.dumps(
            {
                "email": "user@example.com",
                "write-token": {"client_id": "disk-write-client"},
                "org_id": "123456",
            }
        ),
        encoding="utf-8",
    )
    disk = YandexDisk(account="corp", data_dir=str(tmp_path))
    try:
        disk._build_share_payload(access="employees", rights="read")
    except ValueError as exc:
        assert "org_id" in str(exc)
    else:
        raise AssertionError("Expected explicit org_id to be required")


def test_single_account_dispatch_deletes_token_meta(tmp_path):
    """Central dispatch infers the single token file and deletes token_meta."""
    token_path = tmp_path / "auth" / "corp.token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(
        json.dumps(
            {
                "email": "user@example.com",
                "write-token": {"client_id": "disk-write-client"},
                "token_meta": {"write-token": {"client_id": "old"}},
            }
        ),
        encoding="utf-8",
    )
    disk = YandexDisk(data_dir=str(tmp_path))
    disk._config["oauth_apps"] = {
        "catalog": {
            "disk-write": {
                "client_id": "disk-write-client",
                "scopes": ["cloud_api:disk.read"],
            }
        }
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"path":"disk:/team/report.txt"}'
    mock_resp.json.return_value = {"path": "disk:/team/report.txt"}

    with patch.object(disk.session, "request", return_value=mock_resp):
        disk.get_resource_meta("disk:/team/report.txt")

    saved = json.loads(token_path.read_text(encoding="utf-8"))
    assert "token_meta" not in saved


def test_password_requires_password_rights():
    """password cannot be used with plain read/write rights."""
    disk = YandexDisk()
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
    disk = YandexDisk()
    try:
        disk.get_share_info("disk:/team/report.txt")
    except RuntimeError as exc:
        assert "Account is required" in str(exc)
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
    with patch("disk.lib.cli.YandexDisk") as mock_disk_cls, \
         patch("sys.stdout", fake_stdout):
        mock_disk = mock_disk_cls.return_value
        mock_disk.publish_file.return_value = {"path": "disk:/team/report.txt", "public_key": "pk", "public_url": "url", "public_settings": {}}
        with patch("disk.lib.cli.build_share_parser", return_value=parser):
            code = share.main(["publish", "--account", "alex", "--path", "disk:/team/report.txt", "--access", "all", "--rights", "read", "--user-ids", "1,2"])
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
    with patch("disk.lib.cli.YandexDisk") as mock_disk_cls, \
         patch("sys.stderr", fake_stderr), \
         patch("disk.lib.cli.build_share_parser", return_value=parser):
        mock_disk = mock_disk_cls.return_value
        mock_disk.get_share_info.side_effect = RuntimeError("boom")
        code = share.main(["info", "--account", "alex", "--path", "disk:/team/report.txt"])
        assert code == 1
        assert '"error": "boom"' in fake_stderr.getvalue()


def test_ensure_dir_is_idempotent(tmp_path):
    """ensure_dir treats 409 as already exists."""
    disk, _ = disk_with_account(tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 409
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "request", return_value=mock_resp) as mock_request:
        result = disk.ensure_dir("disk:/Проекты")
        mock_request.assert_called_once_with(
            "PUT",
            f"{API_BASE}/v1/disk/resources",
            headers={"Authorization": "OAuth write-token"},
            params={"path": "disk:/Проекты"},
        )
        assert result == {"path": "disk:/Проекты", "created": False}


def test_get_upload_link_mocked(tmp_path):
    """get_upload_link requests upload target with overwrite flag."""
    disk, _ = disk_with_account(tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"href":"https://uploader.disk.yandex.net/abc"}'
    mock_resp.json.return_value = {"href": "https://uploader.disk.yandex.net/abc"}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(disk.session, "request", return_value=mock_resp) as mock_request:
        result = disk.get_upload_link("disk:/Проекты/photo.jpg", overwrite=True)
        mock_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/v1/disk/resources/upload",
            headers={"Authorization": "OAuth write-token"},
            params={"path": "disk:/Проекты/photo.jpg", "overwrite": "true"},
        )
        assert result["href"] == "https://uploader.disk.yandex.net/abc"


def test_upload_file_creates_parents_and_fetches_meta(tmp_path):
    """upload_file creates parents, uploads bytes, and returns normalized metadata."""
    disk, _ = disk_with_account(tmp_path)

    upload_link_resp = MagicMock()
    upload_link_resp.status_code = 200
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
    disk = YandexDisk()
    with patch.object(disk, "upload_file", return_value={"remote_path": "disk:/Docs/report.pdf", "name": "report.pdf", "size": 7, "uploaded": True}), \
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
        assert result["attachment"] == {"fileName": "report.pdf", "url": "url", "size": 7}


def test_upload_requires_local_file():
    """upload_file fails fast when local file is missing."""
    disk = YandexDisk()
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

    with patch("disk.lib.cli.YandexDisk") as mock_disk_cls, \
         patch("sys.stdout", fake_stdout), \
         patch("disk.lib.cli.build_upload_parser", return_value=parser):
        mock_disk = mock_disk_cls.return_value
        mock_disk.upload_and_publish.return_value = {"remote_path": "disk:/Проекты/photo.jpg", "public_url": "url"}
        code = upload.main(argv[1:])
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

    with patch("disk.lib.cli.YandexDisk") as mock_disk_cls, \
         patch("sys.stderr", fake_stderr), \
         patch("disk.lib.cli.build_upload_parser", return_value=parser):
        mock_disk = mock_disk_cls.return_value
        mock_disk.upload_file.side_effect = RuntimeError("boom")
        code = upload.main(argv[1:])
        assert code == 1
        assert '"error": "boom"' in fake_stderr.getvalue()


def test_live_restricted_publish_requires_auth_when_enabled():
    """Optional live test: employees-only publish must reject anonymous public-resource access."""
    account = os.getenv("YANDEX_DISK_LIVE_ACCOUNT")
    data_dir = os.getenv("YANDEX_DISK_LIVE_DATA_DIR")
    org_id = os.getenv("YANDEX_DISK_LIVE_ORG_ID")
    base_path = os.getenv("YANDEX_DISK_LIVE_BASE_PATH")
    if not account or not org_id or not base_path:
        return

    disk = YandexDisk(account=account, data_dir=data_dir)
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
    account = os.getenv("YANDEX_DISK_LIVE_ACCOUNT")
    data_dir = os.getenv("YANDEX_DISK_LIVE_DATA_DIR")
    base_path = os.getenv("YANDEX_DISK_LIVE_BASE_PATH")
    if not account or not base_path:
        return

    disk = YandexDisk(account=account, data_dir=data_dir)
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


if __name__ == "__main__":
    import pytest
    import sys

    raise SystemExit(pytest.main([__file__]))
