from __future__ import annotations

import builtins
import json
import os
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.config import RuntimeContext
from common.oauth_apps import (
    OAuthClientMetadataCaptchaError,
    OAuthClientMetadata,
    configured_oauth_app,
    fetch_yandex_oauth_client_metadata,
    oauth_app_for_client_id,
)
import common.oauth_token_import as token_import
import scripts.oauth_setup as oauth_setup


def verified(email: str, client_id: str):
    """Build a verified-token identity test double."""
    return type("VerifiedTokenIdentity", (), {"email": email, "client_id": client_id})()


def canonical_token(account: str) -> Path:
    return Path.home() / "secrets" / "yandex-office" / f"{account}.token"


def canonical_registry() -> Path:
    return Path.home() / "secrets" / "yandex-office" / "oauth-code-flow.json"


def test_oauth_setup_access_token_prompt_uses_hidden_input(monkeypatch) -> None:
    calls: dict[str, str] = {}

    def fake_getpass(prompt: str) -> str:
        calls["prompt"] = prompt
        return "secret-token"

    monkeypatch.setattr(oauth_setup.getpass, "getpass", fake_getpass)

    assert oauth_setup._read_access_token("Paste: ") == "secret-token"
    assert calls["prompt"] == "Paste: "


def test_oauth_setup_rejects_removed_planning_flags(monkeypatch, tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(workspace)

    for argv, expected in (
        (["--service", "mail"], "unrecognized arguments: --service mail"),
        (["--client-id", "client"], "unrecognized arguments: --client-id client"),
        (["--scope", "mail:imap_ro"], "unrecognized arguments: --scope mail:imap_ro"),
    ):
        monkeypatch.setattr(sys, "argv", ["oauth_setup.py", *argv])
        try:
            oauth_setup.main()
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError(f"{argv[0]} must not remain a supported CLI flag")

        assert expected in capsys.readouterr().err


def test_oauth_setup_bootstraps_from_workspace_cwd(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_dir = workspace / "yandex-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.skill.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=data_dir / "config.agent.json",
        agent_config={"accounts": [{"name": "work", "email": "work@example.com"}]},
        config={
            "accounts": [{"name": "work", "email": "work@example.com"}],
            "oauth_apps": {
                "catalog": {
                    "mail-readonly": {
                        "service": "mail",
                        "client_id": "660686ff45f947f2ac6e3f6495a9ec74",
                        "scopes": ["mail:imap_ro"],
                        "is_default": True,
                    }
                },
            },
        },
    )

    calls: dict[str, object] = {}
    saved: dict[str, object] = {}

    def fake_bootstrap(
        start_path: str | Path,
        *,
        account: str,
        email: str,
        cwd: str | Path | None = None,
        data_dir_override: str | Path | None = None,
    ) -> RuntimeContext:
        calls["start_path"] = str(start_path)
        calls["account"] = account
        calls["email"] = email
        calls["cwd"] = Path(cwd).resolve() if cwd is not None else None
        calls["data_dir_override"] = data_dir_override
        return runtime

    def fake_save(path: Path, token_data: dict) -> None:
        saved["path"] = path
        saved["token_data"] = token_data

    def fake_load(_path: Path) -> dict:
        raise FileNotFoundError

    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", fake_bootstrap)
    monkeypatch.setattr(
        token_import,
        "verify_token_identity",
        lambda *_args, **_kwargs: verified("work@example.com", "660686ff45f947f2ac6e3f6495a9ec74"),
    )
    monkeypatch.setattr(token_import, "save_token_file", fake_save)
    monkeypatch.setattr(token_import, "load_token_file", fake_load)
    monkeypatch.setattr(oauth_setup, "_read_access_token", lambda _prompt="": "token-value")
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "oauth_setup.py",
            "--email",
            "work@example.com",
            "--account",
            "work",
            "--app",
            "mail-readonly",
        ],
    )

    oauth_setup.main()

    assert calls["account"] == "work"
    assert calls["email"] == "work@example.com"
    assert calls["cwd"] == workspace.resolve()
    assert calls["data_dir_override"] is None
    assert saved["path"] == canonical_token("work")
    token_data = saved["token_data"]
    assert token_data["email"] == "work@example.com"
    assert token_data["token-value"] == {
        "client_id": "660686ff45f947f2ac6e3f6495a9ec74",
    }
    assert "token_meta" not in token_data


def test_oauth_setup_without_args_bootstraps_only(monkeypatch, tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_dir = workspace / "yandex-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.skill.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=data_dir / "config.agent.json",
        agent_config={"accounts": []},
        config={"accounts": []},
    )

    calls: dict[str, object] = {}

    def fake_bootstrap(
        start_path: str | Path,
        *,
        account: str | None = None,
        email: str | None = None,
        cwd: str | Path | None = None,
        data_dir_override: str | Path | None = None,
    ) -> RuntimeContext:
        calls["start_path"] = str(start_path)
        calls["account"] = account
        calls["email"] = email
        calls["cwd"] = Path(cwd).resolve() if cwd is not None else None
        calls["data_dir_override"] = data_dir_override
        return runtime

    def fail(*_args, **_kwargs):
        raise AssertionError("OAuth planning/saving should not run in bootstrap-only mode")

    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", fake_bootstrap)
    monkeypatch.setattr(oauth_setup, "plan_oauth_app_setup", fail)
    monkeypatch.setattr(token_import, "save_token_file", fail)
    monkeypatch.setattr(token_import, "load_token_file", fail)
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(sys, "argv", ["oauth_setup.py"])

    oauth_setup.main()

    captured = capsys.readouterr()
    assert calls["account"] is None
    assert calls["email"] is None
    assert calls["cwd"] == workspace.resolve()
    assert calls["data_dir_override"] is None
    assert str(data_dir.resolve()) in captured.out


def test_oauth_setup_bootstraps_without_creating_account_without_token(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_dir = workspace / "yandex-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.skill.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=data_dir / "config.agent.json",
        agent_config={"accounts": [{"name": "alex", "email": "user@example.com"}]},
        config={"accounts": [{"name": "alex", "email": "user@example.com"}]},
    )

    calls: dict[str, object] = {}

    def fake_bootstrap(
        start_path: str | Path,
        *,
        account: str | None = None,
        email: str | None = None,
        cwd: str | Path | None = None,
        data_dir_override: str | Path | None = None,
    ) -> RuntimeContext:
        calls["account"] = account
        calls["email"] = email
        calls["cwd"] = Path(cwd).resolve() if cwd is not None else None
        calls["data_dir_override"] = data_dir_override
        return runtime

    saved: dict[str, object] = {}

    def fail_plan(*_args, **_kwargs):
        raise AssertionError("OAuth planning should not run without OAuth args")

    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", fake_bootstrap)
    monkeypatch.setattr(oauth_setup, "plan_oauth_app_setup", fail_plan)
    monkeypatch.setattr(oauth_setup, "save_token_file", lambda path, token_data: saved.update(path=path, token_data=token_data))
    monkeypatch.setattr(oauth_setup, "load_token_file", lambda _path: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(
        sys,
        "argv",
        ["oauth_setup.py", "--email", "user@example.com", "--account", "alex"],
    )

    oauth_setup.main()

    captured = capsys.readouterr()
    assert calls["account"] == "alex"
    assert calls["email"] == "user@example.com"
    assert calls["cwd"] == workspace.resolve()
    assert calls["data_dir_override"] is None
    assert captured.out == '{"alias":"alex","email":"user@example.com","apps":[]}\n'
    assert saved["path"] == canonical_token("alex")
    assert saved["token_data"] == {"email": "user@example.com"}


def test_oauth_setup_bare_account_bootstraps_token_file(monkeypatch, tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(
        sys,
        "argv",
        ["oauth_setup.py", "--account", "work"],
    )

    oauth_setup.main()

    captured = capsys.readouterr()
    assert captured.out == '{"alias":"work","apps":[]}\n'
    assert json.loads(canonical_token("work").read_text()) == {}

    for argv, expected in (
        (["--email", "work@example.com", "--account", "work"], '{"alias":"work","email":"work@example.com","apps":[]}\n'),
        (["--accounts", "list"], "work\n"),
        (["--accounts", "delete", "--account", "work"], "deleted work\n"),
        (["--accounts", "reset"], "reset 0\n"),
    ):
        monkeypatch.setattr(sys, "argv", ["oauth_setup.py", *argv])
        oauth_setup.main()
        assert capsys.readouterr().out == expected


def test_oauth_setup_account_info_lists_apps(monkeypatch, tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "workspace"
    auth_dir = workspace / "yandex-data" / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "yandex-data" / "config.agent.json").write_text(
        json.dumps(
            {
                "oauth_apps": {
                    "catalog": {
                        "custom-custom-client": {
                            "client_id": "custom-client",
                            "scopes": ["scope:b", "scope:a"],
                        }
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (auth_dir / "work.token").write_text(
        json.dumps(
            {
                "email": "work@example.com",
                "known-token": {"client_id": "660686ff45f947f2ac6e3f6495a9ec74"},
                "custom-token": {"client_id": "custom-client"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(workspace)
    monkeypatch.setattr(sys, "argv", ["oauth_setup.py", "--account", "work"])

    oauth_setup.main()

    assert capsys.readouterr().out == (
        '{"alias":"work","email":"work@example.com",'
        '"apps":["custom(scope:a, scope:b)","mail-readonly"]}\n'
    )


def test_oauth_setup_app_without_identity_imports_verified_account(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(workspace)
    data_dir = workspace / "yandex-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    agent_config_path = data_dir / "config.agent.json"
    agent_config_path.write_text('{"accounts": [{"name": "alex", "email": "user@example.com"}]}\n', encoding="utf-8")

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.skill.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=agent_config_path,
        agent_config={"accounts": [{"name": "alex", "email": "user@example.com"}]},
        config={
            "accounts": [{"name": "alex", "email": "user@example.com"}],
            "oauth_apps": {
                "catalog": {
                    "mail-readonly": {
                        "service": "mail",
                        "client_id": "660686ff45f947f2ac6e3f6495a9ec74",
                        "scopes": ["mail:imap_ro"],
                        "is_default": True,
                    },
                },
            },
        },
    )

    saved: dict[str, object] = {}

    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr(
        token_import,
        "verify_token_identity",
        lambda *_args, **_kwargs: verified("user@example.com", "660686ff45f947f2ac6e3f6495a9ec74"),
    )
    monkeypatch.setattr(token_import, "save_token_file", lambda path, token_data: saved.update(path=path, token_data=token_data))
    monkeypatch.setattr(token_import, "load_token_file", lambda _path: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(oauth_setup, "_read_access_token", lambda _prompt="": "token-value")
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "")
    monkeypatch.setattr(sys, "argv", ["oauth_setup.py", "--app", "mail-readonly"])

    oauth_setup.main()

    assert saved["path"] == canonical_token("user")
    assert saved["token_data"]["email"] == "user@example.com"
    assert saved["token_data"]["token-value"] == {
        "client_id": "660686ff45f947f2ac6e3f6495a9ec74",
    }


def test_oauth_setup_creates_account_from_verified_email(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_dir = workspace / "yandex-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    agent_config_path = data_dir / "config.agent.json"
    agent_config_path.write_text('{"accounts": []}\n', encoding="utf-8")

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.skill.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=agent_config_path,
        agent_config={"accounts": []},
        config={
            "accounts": [],
            "oauth_apps": {
                "catalog": {
                    "mail-readonly": {
                        "service": "mail",
                        "client_id": "660686ff45f947f2ac6e3f6495a9ec74",
                        "scopes": ["mail:imap_ro"],
                        "is_default": True,
                    },
                },
            },
        },
    )

    saved: dict[str, object] = {}

    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr(
        token_import,
        "verify_token_identity",
        lambda *_args, **_kwargs: verified("new.user@example.com", "660686ff45f947f2ac6e3f6495a9ec74"),
    )
    monkeypatch.setattr(token_import, "save_token_file", lambda path, token_data: saved.update(path=path, token_data=token_data))
    monkeypatch.setattr(token_import, "load_token_file", lambda _path: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(oauth_setup, "_read_access_token", lambda _prompt="": "token-value")
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "")
    monkeypatch.setattr(sys, "argv", ["oauth_setup.py", "--app", "mail-readonly"])

    oauth_setup.main()

    assert saved["path"] == canonical_token("new-user")
    assert '"email": "new.user@example.com"' not in agent_config_path.read_text(encoding="utf-8")


def test_oauth_setup_imports_legacy_yandex_disk_token_from_env(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_dir = workspace / "yandex-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.skill.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=data_dir / "config.agent.json",
        agent_config={},
        config={
            "oauth_apps": {
                "catalog": {
                    "disk-read": {
                        "service": "disk",
                        "client_id": "disk-client",
                        "scopes": ["cloud_api:disk.read"],
                    },
                },
            },
        },
    )

    saved: dict[str, object] = {}

    def fail_input(_prompt=""):
        raise AssertionError("legacy env import must not prompt for access_token")

    monkeypatch.setenv("YANDEX_DISK_TOKEN", "legacy-env-token")
    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr(
        token_import,
        "verify_token_identity",
        lambda *_args, **kwargs: verified("legacy@example.com", "disk-client"),
    )
    monkeypatch.setattr(token_import, "save_token_file", lambda path, token_data: saved.update(path=path, token_data=token_data))
    monkeypatch.setattr(token_import, "load_token_file", lambda _path: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(oauth_setup, "_read_access_token", fail_input)
    monkeypatch.setattr(
        sys,
        "argv",
        ["oauth_setup.py", "--from-env", "YANDEX_DISK_TOKEN", "--account", "diskacct"],
    )

    oauth_setup.main()

    captured = capsys.readouterr()
    assert captured.out == "diskacct\n"
    assert "YANDEX_DISK_TOKEN" not in captured.out
    assert saved["path"] == canonical_token("diskacct")
    assert saved["token_data"] == {
        "email": "legacy@example.com",
        "legacy-env-token": {"client_id": "disk-client"},
    }


def test_oauth_setup_code_flow_start_writes_ordered_pending_registry(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_dir = workspace / "yandex-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.skill.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=data_dir / "config.agent.json",
        agent_config={},
        config={
            "urls": {"oauth": "https://oauth.yandex.ru/authorize"},
            "oauth_apps": {
                "catalog": {
                    "mail-readonly": {
                        "service": "mail",
                        "client_id": "mail-client",
                        "scopes": ["mail:imap_ro"],
                        "omit_scope_in_url": True,
                    },
                    "disk-read": {
                        "service": "disk",
                        "client_id": "disk-client",
                        "scopes": ["cloud_api:disk.read"],
                        "omit_scope_in_url": True,
                    },
                },
            },
        },
    )

    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr(sys, "argv", ["oauth_setup.py", "--app", "mail-readonly", "--code-flow", "start"])
    oauth_setup.main()
    monkeypatch.setattr(sys, "argv", ["oauth_setup.py", "--app", "disk-read", "--code-flow", "start"])
    oauth_setup.main()

    captured = capsys.readouterr()
    assert "https://oauth.yandex.ru/authorize?" in captured.out
    assert "response_type=code" in captured.out
    assert "code_challenge_method=S256" in captured.out
    assert "access_token" not in captured.out
    assert "Code lifetime: 10 minutes" in captured.out
    assert "Expires at:" in captured.out
    assert "Check order: links are tried in the order printed" in captured.out
    registry_path = canonical_registry()
    assert registry_path.exists()
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    pending = registry["pending"]
    assert [entry["app_id"] for entry in pending] == ["mail-readonly", "disk-read"]
    assert pending[0]["client_id"] == "mail-client"
    assert pending[1]["client_id"] == "disk-client"
    assert pending[0]["created_at"] < pending[1]["created_at"]
    assert pending[0]["expires_at"] - pending[0]["created_at"] == 600


def test_oauth_setup_code_flow_complete_tries_registry_in_issue_order(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_dir = workspace / "yandex-data"
    registry_path = canonical_registry()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "pending": [
                    {
                        "app_id": "mail-readonly",
                        "client_id": "mail-client",
                        "redirect_uri": "https://oauth.yandex.ru/verification_code",
                        "code_verifier": "mail-verifier",
                        "created_at": 1700000000,
                        "expires_at": 4102444800,
                    },
                    {
                        "app_id": "disk-read",
                        "client_id": "disk-client",
                        "redirect_uri": "https://oauth.yandex.ru/verification_code",
                        "code_verifier": "disk-verifier",
                        "created_at": 1700000001,
                        "expires_at": 4102444800,
                    },
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.skill.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=data_dir / "config.agent.json",
        agent_config={},
        config={"oauth_apps": {"catalog": {"disk-read": {"service": "disk", "client_id": "disk-client"}}}},
    )
    calls: list[tuple[str, str]] = []

    def fake_exchange(*, code: str, client_id: str, redirect_uri: str, code_verifier: str, config: dict) -> dict:
        calls.append((client_id, code_verifier))
        if client_id == "mail-client":
            raise RuntimeError(
                'Yandex authorization-code exchange failed with HTTP 400: '
                '{"error":"invalid_grant","error_description":"Code has expired"}'
            )
        if client_id != "disk-client":
            raise RuntimeError("bad_verification_code: Invalid code")
        return {"access_token": "disk-access-token", "token_type": "bearer"}

    def fake_import(**kwargs):
        calls.append(("import", kwargs["selected_app_id"]))
        return type(
            "ImportResult",
            (),
            {
                "warnings": [],
                "resolved_account": kwargs.get("account") or "user",
                "identity": verified("user@example.com", "disk-client"),
                "token_path": canonical_token(kwargs.get("account") or "user"),
                "token_data": {"email": "user@example.com", "disk-access-token": {"client_id": "disk-client"}},
            },
        )()

    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr(oauth_setup, "_exchange_authorization_code_for_token", fake_exchange, raising=False)
    monkeypatch.setattr(oauth_setup, "import_managed_oauth_token", fake_import)
    monkeypatch.setattr(
        sys,
        "argv",
        ["oauth_setup.py", "--code-flow", "complete", "--code", "short-confirmation-code"],
    )

    oauth_setup.main()

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["status"] == "ok"
    assert report["operation"] == "code_flow_complete"
    assert report["saved_account"] == "user"
    assert report["app_id"] == "disk-read"
    assert report["apps"] == ["disk-read"]
    assert report["token_path"].endswith("/secrets/yandex-office/user.token")
    assert calls == [
        ("mail-client", "mail-verifier"),
        ("disk-client", "disk-verifier"),
        ("import", "disk-read"),
    ]
    registry_after = json.loads(registry_path.read_text(encoding="utf-8"))
    assert [entry["app_id"] for entry in registry_after["pending"]] == ["mail-readonly"]


def test_oauth_setup_imports_generic_env_token_without_app(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_dir = workspace / "yandex-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.skill.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=data_dir / "config.agent.json",
        agent_config={},
        config={
            "oauth_apps": {
                "catalog": {
                    "mail-readonly": {
                        "service": "mail",
                        "client_id": "mail-client",
                        "scopes": ["mail:imap_ro"],
                    },
                },
            },
        },
    )
    saved: dict[str, object] = {}

    def fail_plan(*_args, **_kwargs):
        raise AssertionError("generic env import must not require an OAuth app plan")

    def fail_input(_prompt=""):
        raise AssertionError("generic env import must not prompt for access_token")

    monkeypatch.setenv("YANDEX_ACCESS_TOKEN", "env-token")
    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr(oauth_setup, "plan_oauth_app_setup", fail_plan)
    monkeypatch.setattr(
        token_import,
        "verify_token_identity",
        lambda *_args, **_kwargs: verified("user@example.com", "mail-client"),
    )
    monkeypatch.setattr(token_import, "save_token_file", lambda path, token_data: saved.update(path=path, token_data=token_data))
    monkeypatch.setattr(token_import, "load_token_file", lambda _path: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(oauth_setup, "_read_access_token", fail_input)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "oauth_setup.py",
            "--from-env",
            "YANDEX_ACCESS_TOKEN",
        ],
    )

    oauth_setup.main()

    captured = capsys.readouterr()
    assert captured.out == "user\n"
    assert "YANDEX_ACCESS_TOKEN" not in captured.out
    assert saved["path"] == canonical_token("user")
    assert saved["token_data"] == {
        "email": "user@example.com",
        "env-token": {"client_id": "mail-client"},
    }


def test_managed_import_uses_explicit_account_instead_of_deriving_alias_from_email(monkeypatch, tmp_path: Path) -> None:
    config = {"oauth_apps": {"catalog": {"office-core": {"client_id": "office-client"}}}}
    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        token_import,
        "verify_token_identity",
        lambda *_args, **_kwargs: verified("bdi@example.com", "office-client"),
    )

    result = token_import.import_managed_oauth_token(
        config=config,
        data_dir=data_dir,
        agent_config={},
        agent_config_path=data_dir / "config.agent.json",
        token="office-token",
        account="test",
        selected_app_id="office-core",
    )

    assert result.resolved_account == "test"
    assert result.token_path == canonical_token("test")
    assert json.loads(canonical_token("test").read_text(encoding="utf-8")) == {
        "email": "bdi@example.com",
        "office-token": {"client_id": "office-client"},
    }
    assert not canonical_token("bdi").exists()


def test_managed_import_uses_existing_account_for_verified_email_even_with_different_account_arg(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = {"oauth_apps": {"catalog": {"office-core": {"client_id": "office-client"}}}}
    data_dir = tmp_path / "data"
    auth_dir = data_dir / "auth"
    auth_dir.mkdir(parents=True)
    (auth_dir / "bdi.token").write_text('{"email":"bdi@example.com"}\n', encoding="utf-8")
    monkeypatch.setattr(
        token_import,
        "verify_token_identity",
        lambda *_args, **_kwargs: verified("bdi@example.com", "office-client"),
    )

    result = token_import.import_managed_oauth_token(
        config=config,
        data_dir=data_dir,
        agent_config={},
        agent_config_path=data_dir / "config.agent.json",
        token="office-token",
        account="test",
        selected_app_id="office-core",
    )

    assert result.resolved_account == "bdi"
    assert result.token_path == canonical_token("bdi")
    assert json.loads(canonical_token("bdi").read_text(encoding="utf-8")) == {
        "email": "bdi@example.com",
        "office-token": {"client_id": "office-client"},
    }
    assert not canonical_token("test").exists()
    assert 'Provided --account "test" does not match existing account "bdi"' in "\n".join(result.warnings)


def test_managed_import_issue_48_identity_rules(monkeypatch, tmp_path: Path) -> None:
    config = {"oauth_apps": {"catalog": {"mail": {"client_id": "mail-client"}}}}
    cases = [
        ("example-user", "example-user@yandex.ru", None, "example-user", ""),
        ("verified@example.com", "wrong@example.com", "manual", "manual", "Provided --email"),
    ]
    for identity_email, email_arg, account_arg, alias, warning in cases:
        monkeypatch.setattr(
            token_import,
            "verify_token_identity",
            lambda *_args, email=identity_email, **_kwargs: verified(email, "mail-client"),
        )
        result = token_import.import_managed_oauth_token(
            config=config,
            data_dir=tmp_path / alias,
            agent_config={},
            agent_config_path=tmp_path / alias / "config.agent.json",
            token=f"{alias}-token",
            email=email_arg,
            account=account_arg,
        )
        assert result.token_path.name == f"{alias}.token"
        assert bool(warning) == bool(result.warnings)
        assert not warning or warning in "\n".join(result.warnings)


def test_oauth_setup_warns_on_preconfigured_app_mismatch(monkeypatch, tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_dir = workspace / "yandex-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    agent_config_path = data_dir / "config.agent.json"
    agent_config_path.write_text('{"accounts": [{"name": "alex", "email": "user@example.com"}]}\n', encoding="utf-8")

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.skill.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=agent_config_path,
        agent_config={"accounts": [{"name": "alex", "email": "user@example.com"}]},
        config={"accounts": [{"name": "alex", "email": "user@example.com"}], "oauth_apps": {"catalog": {}}},
    )
    runtime.config["oauth_apps"]["catalog"]["mail-readonly"] = {
        "service": "mail",
        "client_id": "selected-client",
        "scopes": ["mail:imap_ro"],
    }

    saved: dict[str, object] = {}

    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr(
        token_import,
        "verify_token_identity",
        lambda *_args, **_kwargs: verified("user@example.com", "other-client"),
    )
    monkeypatch.setattr(
        token_import,
        "oauth_app_for_client_id",
        lambda *_args, **_kwargs: type("MatchedApp", (), {"app_id": "mail-readwrite"})(),
    )
    monkeypatch.setattr(token_import, "save_token_file", lambda path, token_data: saved.update(path=path, token_data=token_data))
    monkeypatch.setattr(token_import, "load_token_file", lambda _path: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(oauth_setup, "_read_access_token", lambda _prompt="": "token-value")
    monkeypatch.setattr(sys, "argv", ["oauth_setup.py", "--app", "mail-readonly"])

    oauth_setup.main()

    captured = capsys.readouterr()
    assert "non-standard token" in captured.err
    assert saved["token_data"]["token-value"] == {"client_id": "other-client"}
    assert "token_meta" not in saved["token_data"]


def test_oauth_setup_accepts_app_without_service(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_dir = workspace / "yandex-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    agent_config_path = data_dir / "config.agent.json"
    agent_config_path.write_text('{"accounts": [{"name": "alex", "email": "user@example.com"}]}\n', encoding="utf-8")

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.skill.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=agent_config_path,
        agent_config={"accounts": [{"name": "alex", "email": "user@example.com"}]},
        config={
            "accounts": [{"name": "alex", "email": "user@example.com"}],
            "oauth_apps": {
                "catalog": {
                    "office-core": {
                        "service": ["calendar", "disk", "mail", "telemost"],
                        "client_id": "office-core-client",
                        "scopes": [
                            "calendar:all",
                            "cloud_api:disk.read",
                            "cloud_api:disk.write",
                            "mail:imap_ro",
                            "telemost-api:conferences.create",
                            "telemost-api:conferences.read",
                        ],
                    }
                }
            },
        },
    )

    saved: dict[str, object] = {}

    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr(
        token_import,
        "verify_token_identity",
        lambda *_args, **_kwargs: verified("user@example.com", "office-core-client"),
    )
    monkeypatch.setattr(token_import, "save_token_file", lambda path, token_data: saved.update(path=path, token_data=token_data))
    monkeypatch.setattr(token_import, "load_token_file", lambda _path: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(oauth_setup, "_read_access_token", lambda _prompt="": "token-value")
    monkeypatch.setattr(sys, "argv", ["oauth_setup.py", "--app", "office-core"])

    oauth_setup.main()

    token_data = saved["token_data"]
    assert token_data["token-value"] == {"client_id": "office-core-client"}
    assert not any(key.startswith("token.") for key in token_data)


def test_oauth_setup_propagates_multi_service_app_token(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_dir = workspace / "yandex-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    agent_config_path = data_dir / "config.agent.json"
    agent_config_path.write_text('{"accounts": [{"name": "alex", "email": "user@example.com"}]}\n', encoding="utf-8")

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.skill.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=agent_config_path,
        agent_config={"accounts": [{"name": "alex", "email": "user@example.com"}]},
        config={
            "accounts": [{"name": "alex", "email": "user@example.com"}],
            "oauth_apps": {
                "catalog": {
                    "office-core": {
                        "service": ["calendar", "disk", "mail", "telemost"],
                        "client_id": "office-core-client",
                        "scopes": [
                            "calendar:all",
                            "cloud_api:disk.read",
                            "cloud_api:disk.write",
                            "mail:imap_ro",
                            "telemost-api:conferences.create",
                            "telemost-api:conferences.read",
                        ],
                    }
                }
            },
        },
    )

    saved: dict[str, object] = {}

    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr(
        token_import,
        "verify_token_identity",
        lambda *_args, **_kwargs: verified("user@example.com", "office-core-client"),
    )
    monkeypatch.setattr(token_import, "save_token_file", lambda path, token_data: saved.update(path=path, token_data=token_data))
    monkeypatch.setattr(token_import, "load_token_file", lambda _path: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(oauth_setup, "_read_access_token", lambda _prompt="": "token-value")
    monkeypatch.setattr(sys, "argv", ["oauth_setup.py", "--app", "office-core"])

    oauth_setup.main()

    token_data = saved["token_data"]
    assert token_data["token-value"] == {"client_id": "office-core-client"}
    assert "token_meta" not in token_data


def test_oauth_setup_imports_custom_app_from_live_metadata(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_dir = workspace / "yandex-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    agent_config_path = data_dir / "config.agent.json"
    agent_config_path.write_text('{"accounts": [{"name": "alex", "email": "user@example.com"}]}\n', encoding="utf-8")

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.skill.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=agent_config_path,
        agent_config={"accounts": [{"name": "alex", "email": "user@example.com"}]},
        config={"accounts": [{"name": "alex", "email": "user@example.com"}]},
    )

    saved: dict[str, object] = {}

    def fail_input(_prompt=""):
        raise AssertionError("env import must not prompt for access_token")

    monkeypatch.setenv("YANDEX_ACCESS_TOKEN", "token-value")
    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr(
        token_import,
        "verify_token_identity",
        lambda *_args, **_kwargs: verified("user@example.com", "custom-client"),
    )
    monkeypatch.setattr(token_import, "oauth_app_for_client_id", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        token_import,
        "fetch_yandex_oauth_client_metadata",
        lambda _config, *, client_id: OAuthClientMetadata(
            client_id=client_id,
            app_name="Yandex Live Custom App",
            scopes=["scope:b", "scope:a"],
        ),
    )
    monkeypatch.setattr(token_import, "save_token_file", lambda path, token_data: saved.update(path=path, token_data=token_data))
    monkeypatch.setattr(token_import, "load_token_file", lambda _path: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(oauth_setup, "_read_access_token", fail_input)
    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt="": (_ for _ in ()).throw(AssertionError("custom app import must not prompt")),
    )
    monkeypatch.setattr(sys, "argv", ["oauth_setup.py", "--from-env", "YANDEX_ACCESS_TOKEN"])

    oauth_setup.main()

    assert saved["token_data"]["token-value"] == {"client_id": "custom-client"}
    assert "token_meta" not in saved["token_data"]
    agent_config = json.loads(agent_config_path.read_text(encoding="utf-8"))
    assert "accounts" not in agent_config
    assert agent_config["oauth_apps"]["catalog"]["custom-custom-client"] == {
        "client_id": "custom-client",
        "scopes": ["scope:a", "scope:b"],
        "name": "Yandex Live Custom App",
        "omit_scope_in_url": False,
    }


def test_managed_import_unknown_client_requires_live_metadata(monkeypatch, tmp_path: Path) -> None:
    config = {"oauth_apps": {"catalog": {}}}
    agent_config_path = tmp_path / "config.agent.json"
    data_dir = tmp_path / "data"

    monkeypatch.setattr(
        token_import,
        "verify_token_identity",
        lambda *_args, **_kwargs: verified("user@example.com", "custom-client"),
    )
    monkeypatch.setattr(token_import, "oauth_app_for_client_id", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        token_import,
        "fetch_yandex_oauth_client_metadata",
        lambda _config, *, client_id: (_ for _ in ()).throw(RuntimeError("HTTP 302")),
    )

    try:
        token_import.import_managed_oauth_token(
            config=config,
            data_dir=data_dir,
            agent_config={},
            agent_config_path=agent_config_path,
            token="token-value",
            service="mail",
        )
    except RuntimeError as exc:
        assert "live OAuth client metadata lookup failed" in str(exc)
    else:
        raise AssertionError("unknown client import should fail without live metadata")

    assert not agent_config_path.exists()
    assert not (data_dir / "auth" / "user.token").exists()


def test_managed_import_marks_captcha_client_unresolved(monkeypatch, tmp_path: Path) -> None:
    config = {"oauth_apps": {"catalog": {}}}
    agent_config_path = tmp_path / "config.agent.json"
    data_dir = tmp_path / "data"

    monkeypatch.setattr(
        token_import,
        "verify_token_identity",
        lambda *_args, **_kwargs: verified("user@example.com", "custom-client"),
    )
    monkeypatch.setattr(token_import, "oauth_app_for_client_id", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        token_import,
        "fetch_yandex_oauth_client_metadata",
        lambda _config, *, client_id: (_ for _ in ()).throw(
            OAuthClientMetadataCaptchaError("captcha JSON")
        ),
    )

    result = token_import.import_managed_oauth_token(
        config=config,
        data_dir=data_dir,
        agent_config={},
        agent_config_path=agent_config_path,
        token="token-value",
        service="mail",
    )

    assert result.resolved_account == "user"
    assert result.token_data["token-value"] == {"client_id": "custom-client"}
    assert any("CAPTCHA JSON" in warning for warning in result.warnings)
    agent_config = json.loads(agent_config_path.read_text(encoding="utf-8"))
    assert agent_config["oauth_apps"]["catalog"]["custom-custom-client"] == {
        "client_id": "custom-client",
        "scopes": ["unresolved"],
        "name": "Unresolved Yandex OAuth app custom-c",
        "omit_scope_in_url": False,
    }


def test_oauth_setup_uses_data_dir_parent_as_bootstrap_cwd(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    data_dir = workspace / "custom-yandex"
    data_dir.mkdir(parents=True, exist_ok=True)

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.skill.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=data_dir / "config.agent.json",
        agent_config={"accounts": [{"name": "work", "email": "work@example.com"}]},
        config={
            "accounts": [{"name": "work", "email": "work@example.com"}],
            "oauth_apps": {
                "catalog": {
                    "mail-readonly": {
                        "service": "mail",
                        "client_id": "660686ff45f947f2ac6e3f6495a9ec74",
                        "scopes": ["mail:imap_ro"],
                        "is_default": True,
                    },
                },
            },
        },
    )

    calls: dict[str, object] = {}

    def fake_bootstrap(
        start_path: str | Path,
        *,
        account: str,
        email: str,
        cwd: str | Path | None = None,
        data_dir_override: str | Path | None = None,
    ) -> RuntimeContext:
        calls["cwd"] = Path(cwd).resolve() if cwd is not None else None
        calls["data_dir_override"] = (
            Path(data_dir_override).resolve() if data_dir_override is not None else None
        )
        return runtime

    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", fake_bootstrap)
    monkeypatch.setattr(
        token_import,
        "verify_token_identity",
        lambda *_args, **_kwargs: verified("work@example.com", "660686ff45f947f2ac6e3f6495a9ec74"),
    )
    monkeypatch.setattr(token_import, "save_token_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(token_import, "load_token_file", lambda _path: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(oauth_setup, "_read_access_token", lambda _prompt="": "token-value")
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "")
    monkeypatch.chdir(ROOT_DIR)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "oauth_setup.py",
            "--email",
            "work@example.com",
            "--account",
            "work",
            "--app",
            "mail-readonly",
            "--data-dir",
            str(data_dir),
        ],
    )

    oauth_setup.main()

    assert calls["cwd"] == ROOT_DIR.resolve()
    assert calls["data_dir_override"] == data_dir.resolve()


def test_catalog_entry_can_span_multiple_services() -> None:
    config = {
        "oauth_apps": {
            "catalog": {
                "office-core": {
                    "service": ["calendar", "disk", "mail", "telemost"],
                    "client_id": "office-core-client",
                    "scopes": [
                        "calendar:all",
                        "cloud_api:disk.read",
                        "cloud_api:disk.write",
                        "mail:imap_ro",
                        "telemost-api:conferences.create",
                        "telemost-api:conferences.read",
                    ],
                },
            },
        }
    }

    disk_app = configured_oauth_app(config, "disk", "office-core")
    assert disk_app is not None
    assert disk_app.service == "disk"
    assert disk_app.client_id == "office-core-client"
    assert "cloud_api:disk.write" in disk_app.scopes

    matched = oauth_app_for_client_id(config, "office-core-client", service="telemost")
    assert matched is not None
    assert matched.service == "telemost"
    assert matched.app_id == "office-core"


def test_oauth_app_for_client_id_returns_service_less_agent_local_app() -> None:
    config = {
        "oauth_apps": {
            "catalog": {
                "custom-cloud": {
                    "client_id": "cloud-client",
                    "name": "Yandex.Cloud",
                    "scopes": ["cloud:auth"],
                    "omit_scope_in_url": False,
                },
            },
        }
    }

    matched = oauth_app_for_client_id(config, "cloud-client")

    assert matched is not None
    assert matched.service == ""
    assert matched.services == ()
    assert matched.app_id == "custom-cloud"
    assert matched.app_name == "Yandex.Cloud"
    assert matched.scopes == ["cloud:auth"]
    service_match = oauth_app_for_client_id(config, "cloud-client", service="disk")
    assert service_match is not None
    assert service_match.service == "disk"
    assert service_match.services == ()


def test_oauth_client_metadata_lookup_reports_redirect_as_unresolved(monkeypatch) -> None:
    class FakeNoRedirect:
        pass

    class FakeOpener:
        def open(self, request, timeout):
            from urllib.error import HTTPError

            assert request.full_url == "https://oauth.yandex.com/client/flying-saucer/info?format=json"
            raise HTTPError(
                request.full_url,
                302,
                "Found",
                {},
                None,
            )

    monkeypatch.setattr("common.oauth_apps._NoRedirect", FakeNoRedirect)
    monkeypatch.setattr("common.oauth_apps.build_opener", lambda _handler: FakeOpener())

    try:
        fetch_yandex_oauth_client_metadata({}, client_id="flying-saucer")
    except RuntimeError as exc:
        assert "HTTP 302" in str(exc)
    else:
        raise AssertionError("unresolvable client id should fail")


def test_oauth_client_metadata_lookup_reports_captcha_json(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

    class FakeNoRedirect:
        pass

    class FakeOpener:
        def __init__(self) -> None:
            self.calls = 0

        def open(self, request, timeout):
            self.calls += 1
            return FakeResponse(
                {
                    "type": "captcha",
                    "captcha": {"captcha-page": "https://oauth.yandex.com/showcaptcha"},
                }
            )

    opener = FakeOpener()
    monkeypatch.setattr("common.oauth_apps._NoRedirect", FakeNoRedirect)
    monkeypatch.setattr("common.oauth_apps.build_opener", lambda _handler: opener)

    try:
        fetch_yandex_oauth_client_metadata({}, client_id="client-id")
    except OAuthClientMetadataCaptchaError as exc:
        assert "captcha JSON" in str(exc)
    else:
        raise AssertionError("captcha JSON must be unresolved metadata")

    assert opener.calls == 1
