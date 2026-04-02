from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.auth import canonical_token_key, resolve_token, TokenResolutionError
from common.config import load_runtime_context


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_runtime_context_uses_cwd_agent_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo" / "skills" / "yandex"
    script_path = repo / "mail" / "scripts" / "fetch_emails.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("", encoding="utf-8")

    write_json(
        repo / "config.json",
        {
            "data_dir": "yandex-data",
            "mail": {"filters": {"sender": "keeper@telemost.yandex.ru"}},
        },
    )

    workspace = tmp_path / "workspace"
    write_json(
        workspace / "yandex-data" / "config.agent.json",
        {
            "mailboxes": [{"name": "primary", "email": "user@example.com"}],
        },
    )

    runtime = load_runtime_context(script_path, cwd=workspace)

    assert runtime.data_dir == (workspace / "yandex-data").resolve()
    assert runtime.config["mailboxes"][0]["name"] == "primary"


def test_resolve_token_uses_canonical_service_key(tmp_path: Path) -> None:
    data_dir = tmp_path / "workspace" / "yandex-data"
    token_path = data_dir / "auth" / "corp.token"
    write_json(
        token_path,
        {
            "email": "user@example.com",
            "token.directory": "directory_token",
        },
    )

    resolved = resolve_token(
        account="corp",
        skill="directory",
        data_dir=data_dir,
        config={"urls": {"oauth": "https://oauth.yandex.ru/authorize"}},
        required_scopes=["directory:read_users"],
    )

    assert resolved.token == "directory_token"
    assert canonical_token_key("directory") == "token.directory"
    assert resolved.source_key == "token.directory"


def test_resolve_token_requires_service_specific_token(tmp_path: Path) -> None:
    data_dir = tmp_path / "workspace" / "yandex-data"
    token_path = data_dir / "auth" / "bdi.token"
    write_json(
        token_path,
        {
            "email": "user@example.com",
        },
    )

    try:
        resolve_token(
            account="bdi",
            skill="mail",
            data_dir=data_dir,
            config={"urls": {"oauth": "https://oauth.yandex.ru/authorize"}},
            required_scopes=["mail:imap_ro"],
        )
    except TokenResolutionError as exc:
        assert "No token resolved for mail account bdi" in str(exc)
    else:
        raise AssertionError("Expected TokenResolutionError for missing token.mail")
