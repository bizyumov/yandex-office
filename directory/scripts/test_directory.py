#!/usr/bin/env python3
"""Tests for the Yandex 360 Directory client (directory/scripts/list.py)."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from directory.scripts.list import DirectoryApi  # noqa: E402

DIR_CLIENT_ID = "directory-client-id"
DIR_SCOPES = [
    "directory:read_users",
    "directory:write_users",
    "directory:read_organization",
    "directory:read_departments",
    "directory:read_groups",
]


def directory_with_account(tmp_path: Path, *, account: str = "alice", token: str = "dir-token") -> DirectoryApi:
    """Create a DirectoryApi backed by a real token-file entry + catalog app."""
    token_path = tmp_path / "auth" / f"{account}.token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(
        json.dumps({"email": f"{account}@example.com", token: {"client_id": DIR_CLIENT_ID}}),
        encoding="utf-8",
    )
    api = DirectoryApi(account=account, data_dir=str(tmp_path))
    api._config["oauth_apps"] = {
        "catalog": {"directory-full": {"client_id": DIR_CLIENT_ID, "scopes": DIR_SCOPES}}
    }
    return api


def _ok(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.content = b"{}"
    resp.json.return_value = payload
    return resp


# ── regression guards ───────────────────────────────────────────────

def test_host_is_api360_not_cloud_api():
    """The Directory client must target api360.yandex.net (never cloud-api, the 404 trap)."""
    api = DirectoryApi()
    assert api.api_base == "https://api360.yandex.net"
    assert "cloud-api" not in api.api_base


def test_resolve_org_id_explicit_skips_api(tmp_path):
    """An explicit org id is used verbatim with no API call."""
    api = directory_with_account(tmp_path)
    assert api.resolve_org_id(123456) == "123456"


# ── request shape (mocked HTTP) ─────────────────────────────────────

def test_list_users_mocked(tmp_path):
    api = directory_with_account(tmp_path)
    payload = {"users": [{"id": "1"}], "page": 1, "pages": 1, "perPage": 1000, "total": 1}
    with patch.object(api.session, "request", return_value=_ok(payload)) as req:
        out = api.list_users("123456", page=1, per_page=1000)
    assert out["total"] == 1
    assert req.call_args.args[0] == "GET"
    assert req.call_args.args[1] == "https://api360.yandex.net/directory/v1/org/123456/users"
    assert req.call_args.kwargs["params"] == {"page": 1, "perPage": 1000}
    assert req.call_args.kwargs["headers"]["Authorization"].startswith("OAuth ")


def test_get_user_mocked(tmp_path):
    api = directory_with_account(tmp_path)
    payload = {"id": "1120000000000001", "email": "a@example.com", "displayName": "Foo Bar"}
    with patch.object(api.session, "request", return_value=_ok(payload)) as req:
        out = api.get_user("123456", "1120000000000001")
    assert out["displayName"] == "Foo Bar"
    assert req.call_args.args[0] == "GET"
    assert req.call_args.args[1] == "https://api360.yandex.net/directory/v1/org/123456/users/1120000000000001"
    assert req.call_args.kwargs["headers"]["Authorization"].startswith("OAuth ")


def test_update_user_displayname_mocked(tmp_path):
    """The unique-value operation: PATCH displayName via the correct host."""
    api = directory_with_account(tmp_path)
    payload = {"id": "1120000000000001", "displayName": "Имя Фамилия"}
    with patch.object(api.session, "request", return_value=_ok(payload)) as req:
        out = api.update_user("123456", "1120000000000001", {"displayName": "Имя Фамилия"})
    assert out["displayName"] == "Имя Фамилия"
    assert req.call_args.args[0] == "PATCH"
    assert req.call_args.args[1] == "https://api360.yandex.net/directory/v1/org/123456/users/1120000000000001"
    assert req.call_args.kwargs["json"] == {"displayName": "Имя Фамилия"}
    assert req.call_args.kwargs["headers"]["Authorization"].startswith("OAuth ")


def test_update_user_never_targets_cloud_api_host(tmp_path):
    """Regression guard: a Directory PATCH must never hit cloud-api.yandex.net."""
    api = directory_with_account(tmp_path)
    with patch.object(api.session, "request", return_value=_ok({"id": "1"})) as req:
        api.update_user("123456", "1", {"displayName": "X"})
    assert req.call_args.args[1].startswith("https://api360.yandex.net/")
    assert "cloud-api" not in req.call_args.args[1]
