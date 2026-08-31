from __future__ import annotations

import json
from pathlib import Path

from common.auth import resolve_token
from common.config import (
    AUTH_PATH,
    LEGACY_AUTH_DIR_NAME,
    RuntimeContext,
    bootstrap_runtime_context,
    list_token_accounts,
    resolve_legacy_auth_path,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def runtime_context(tmp_path: Path) -> RuntimeContext:
    data_dir = tmp_path / "runtime" / "yandex-data"
    config_path = tmp_path / "config.skill.json"
    agent_config_path = data_dir / "config.agent.json"
    return RuntimeContext(
        skill_root=tmp_path,
        cwd=tmp_path,
        global_config_path=config_path,
        global_config={},
        data_dir=data_dir,
        agent_config_path=agent_config_path,
        agent_config={},
        config={},
    )


def test_auth_path_declarations_do_not_embed_runtime_placeholders(tmp_path: Path) -> None:
    data_dir = tmp_path / "runtime" / "yandex-data"

    assert AUTH_PATH == Path("~/secrets/yandex-office")
    assert LEGACY_AUTH_DIR_NAME == "auth"
    assert resolve_legacy_auth_path(data_dir) == data_dir.resolve() / "auth"
    assert "{" not in str(AUTH_PATH)
    assert "{" not in LEGACY_AUTH_DIR_NAME


def test_runtime_auth_file_uses_standard_user_secrets_directory(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    path = runtime_context(tmp_path).auth_file("work")

    assert path == home / "secrets" / "yandex-office" / "work.token"


def test_account_listing_migrates_legacy_token_and_warns(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    data_dir = tmp_path / "runtime" / "yandex-data"
    legacy_path = data_dir / "auth" / "work.token"
    canonical_path = home / "secrets" / "yandex-office" / "work.token"
    write_json(
        legacy_path,
        {"email": "account@example.test", "token-value": {"client_id": "client-id"}},
    )

    accounts = list_token_accounts(data_dir)

    captured = capsys.readouterr()
    assert accounts[0]["token_path"] == str(canonical_path)
    assert canonical_path.exists()
    assert not legacy_path.exists()
    assert captured.err == (
        "WARNING: Legacy Yandex Office credentials were found and successfully moved "
        "to ~/secrets/yandex-office.\n"
    )


def test_account_listing_prefers_canonical_token_without_touching_legacy(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    data_dir = tmp_path / "runtime" / "yandex-data"
    canonical_path = home / "secrets" / "yandex-office" / "work.token"
    legacy_path = data_dir / "auth" / "work.token"
    write_json(canonical_path, {"email": "canonical@example.test"})
    write_json(legacy_path, {"email": "legacy@example.test"})

    accounts = list_token_accounts(data_dir)

    captured = capsys.readouterr()
    assert accounts == [
        {
            "name": "work",
            "alias": "work",
            "email": "canonical@example.test",
            "token_path": str(canonical_path),
            "tokens": {},
        }
    ]
    assert legacy_path.exists()
    assert captured.err == ""


def test_resolve_token_migrates_requested_legacy_account(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    data_dir = tmp_path / "runtime" / "yandex-data"
    legacy_path = data_dir / "auth" / "work.token"
    canonical_path = home / "secrets" / "yandex-office" / "work.token"
    write_json(
        legacy_path,
        {
            "email": "account@example.test",
            "token-value": {"client_id": "client-id", "scopes": ["mail:imap_ro"]},
        },
    )

    resolved = resolve_token(
        account="work",
        skill="mail",
        data_dir=data_dir,
        config={},
        required_scopes=["mail:imap_ro"],
    )

    captured = capsys.readouterr()
    assert resolved.token_path == canonical_path
    assert canonical_path.exists()
    assert not legacy_path.exists()
    assert "successfully moved" in captured.err


def test_bootstrap_does_not_create_legacy_auth_directory(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    repo = tmp_path / "repo"
    script_path = repo / "scripts" / "oauth_setup.py"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("", encoding="utf-8")
    write_json(repo / "config.skill.json", {})
    write_json(repo / "config.agent.example.json", {})
    workspace = tmp_path / "workspace"

    runtime = bootstrap_runtime_context(script_path, cwd=workspace)

    assert not (runtime.data_dir / "auth").exists()
    assert (runtime.data_dir / "incoming").is_dir()
    assert (runtime.data_dir / "meetings").is_dir()
