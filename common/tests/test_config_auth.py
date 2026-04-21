from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.auth import canonical_token_key, resolve_token, TokenResolutionError
from common.config import bootstrap_runtime_context, load_runtime_context


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_runtime_context_uses_cwd_agent_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo" / "skills" / "yandex"
    script_path = repo / "mail" / "scripts" / "fetch_emails.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("", encoding="utf-8")

    write_json(
        repo / "config.skill.json",
        {
            "mail": {"filters": {"sender": "keeper@telemost.yandex.ru"}},
        },
    )

    workspace = tmp_path / "workspace"
    write_json(
        workspace / "yandex-data" / "config.agent.json",
        {
            "accounts": [{"name": "primary", "email": "user@example.com"}],
        },
    )

    runtime = load_runtime_context(script_path, cwd=workspace)

    assert runtime.data_dir == (workspace / "yandex-data").resolve()
    assert runtime.config["accounts"][0]["name"] == "primary"


def test_bootstrap_runtime_context_initializes_data_dir(tmp_path: Path) -> None:
    repo = tmp_path / "repo" / "skills" / "yandex"
    script_path = repo / "scripts" / "oauth_setup.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("", encoding="utf-8")

    write_json(
        repo / "config.skill.json",
        {
            "urls": {"oauth": "https://oauth.yandex.ru/authorize"},
        },
    )
    write_json(
        repo / "config.agent.example.json",
        {
            "accounts": [],
            "mail": {"fetch": {"sleep_seconds": 0.0}},
        },
    )

    workspace = tmp_path / "workspace" / "velizar"
    runtime = bootstrap_runtime_context(script_path, cwd=workspace)

    assert (repo / "config.skill.json").exists()
    assert not (repo / "config.json").exists()
    assert runtime.data_dir == (workspace / "yandex-data").resolve()
    assert (workspace / "yandex-data" / "auth").is_dir()
    assert (workspace / "yandex-data" / "incoming").is_dir()
    assert (workspace / "yandex-data" / "meetings").is_dir()
    assert runtime.config["accounts"] == []


def test_load_runtime_context_accepts_explicit_data_dir_override(tmp_path: Path) -> None:
    repo = tmp_path / "repo" / "skills" / "yandex"
    script_path = repo / "mail" / "scripts" / "fetch_emails.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("", encoding="utf-8")

    write_json(repo / "config.skill.json", {})

    external_data_dir = tmp_path / "workspace" / "custom-yandex"
    write_json(
        external_data_dir / "config.agent.json",
        {
            "accounts": [{"name": "work", "email": "work@example.com"}],
        },
    )

    runtime = load_runtime_context(
        script_path,
        cwd=repo,
        data_dir_override=external_data_dir,
        require_agent_config=True,
        require_external_data_dir=True,
    )

    assert runtime.data_dir == external_data_dir.resolve()
    assert runtime.config["accounts"][0]["name"] == "work"


def test_bootstrap_runtime_context_accepts_explicit_data_dir_override(tmp_path: Path) -> None:
    repo = tmp_path / "repo" / "skills" / "yandex"
    script_path = repo / "scripts" / "oauth_setup.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("", encoding="utf-8")

    write_json(repo / "config.skill.json", {})
    write_json(repo / "config.agent.example.json", {"accounts": []})

    workspace = tmp_path / "workspace"
    external_data_dir = workspace / "custom-yandex"
    runtime = bootstrap_runtime_context(
        script_path,
        cwd=repo,
        data_dir_override=external_data_dir,
    )

    assert runtime.data_dir == external_data_dir.resolve()
    assert (external_data_dir / "auth").is_dir()
    assert (external_data_dir / "incoming").is_dir()
    assert (external_data_dir / "meetings").is_dir()
    assert runtime.config["accounts"] == []


def test_load_runtime_context_rejects_data_dir_inside_skill_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo" / "skills" / "yandex"
    script_path = repo / "mail" / "scripts" / "fetch_emails.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("", encoding="utf-8")

    write_json(repo / "config.skill.json", {})

    try:
        load_runtime_context(
            script_path,
            cwd=repo,
            require_agent_config=True,
            require_external_data_dir=True,
        )
    except RuntimeError as exc:
        assert "inside the shared skill tree" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for repo-local data_dir resolution")


def test_load_runtime_context_requires_agent_config_for_external_data_dir(tmp_path: Path) -> None:
    repo = tmp_path / "repo" / "skills" / "yandex"
    script_path = repo / "mail" / "scripts" / "fetch_emails.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("", encoding="utf-8")

    workspace = tmp_path / "workspace"
    write_json(repo / "config.skill.json", {})

    try:
        load_runtime_context(
            script_path,
            cwd=repo,
            require_agent_config=True,
            require_external_data_dir=True,
        )
    except RuntimeError as exc:
        assert "inside the shared skill tree" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for repo-local data_dir resolution")


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
    token_path = data_dir / "auth" / "alex.token"
    write_json(
        token_path,
        {
            "email": "user@example.com",
        },
    )

    try:
        resolve_token(
            account="alex",
            skill="mail",
            data_dir=data_dir,
            config={"urls": {"oauth": "https://oauth.yandex.ru/authorize"}},
            required_scopes=["mail:imap_ro"],
        )
    except TokenResolutionError as exc:
        assert "No token resolved for mail account alex" in str(exc)
    else:
        raise AssertionError("Expected TokenResolutionError for missing token.mail")
