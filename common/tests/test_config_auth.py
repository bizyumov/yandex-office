from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.auth import canonical_token_key, resolve_token
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


def test_resolve_token_bootstraps_directory_alias(tmp_path: Path) -> None:
    data_dir = tmp_path / "workspace" / "yandex-data"
    token_path = data_dir / "auth" / "corp.token"
    write_json(
        token_path,
        {
            "email": "user@example.com",
            "token.org": "y0_directory",
        },
    )

    resolved = resolve_token(
        account="corp",
        skill="directory",
        data_dir=data_dir,
        config={"urls": {"oauth": "https://oauth.yandex.ru/authorize"}},
        required_scopes=["directory:read_users"],
    )

    assert resolved.token == "y0_directory"
    assert canonical_token_key("directory") == "token.directory"
    stored = json.loads(token_path.read_text(encoding="utf-8"))
    assert stored["token.directory"] == "y0_directory"


def test_resolve_token_falls_back_to_token_auth(tmp_path: Path) -> None:
    data_dir = tmp_path / "workspace" / "yandex-data"
    token_path = data_dir / "auth" / "bdi.token"
    write_json(
        token_path,
        {
            "email": "user@example.com",
            "token.auth": "y0_auth",
        },
    )

    resolved = resolve_token(
        account="bdi",
        skill="mail",
        data_dir=data_dir,
        config={"urls": {"oauth": "https://oauth.yandex.ru/authorize"}},
        required_scopes=["mail:imap_ro"],
    )

    assert resolved.source_key == "token.auth"
    stored = json.loads(token_path.read_text(encoding="utf-8"))
    assert stored["token.mail"] == "y0_auth"
