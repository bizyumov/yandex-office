from __future__ import annotations

import builtins
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.config import RuntimeContext
from common.oauth_apps import OAuthSetupPlan, list_service_profiles
import scripts.oauth_setup as oauth_setup


def test_oauth_setup_bootstraps_from_workspace_cwd(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_dir = workspace / "yandex-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=data_dir / "config.agent.json",
        agent_config={"accounts": [{"name": "work", "email": "work@example.com"}]},
        config={"accounts": [{"name": "work", "email": "work@example.com"}]},
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

    def fake_plan(config, *, service, app_id=None, client_id=None, extra_scopes=None):
        return OAuthSetupPlan(
            service=service,
            client_id="client-id",
            scopes=["mail:imap_ro"],
            auth_url="https://oauth.yandex.ru/authorize?response_type=token&client_id=client-id",
            mode="configured_app",
            include_scope_in_url=False,
            app_id="mail-readonly",
            app_name="OpenClaw Yandex Mail Readonly",
        )

    def fake_profiles(_config, _service):
        return [
            type(
                "Profile",
                (),
                {
                    "app_id": "mail-readonly",
                    "access_class": "read-only",
                    "auth_url": "https://oauth.yandex.ru/default",
                    "is_default": True,
                },
            )(),
            type(
                "Profile",
                (),
                {
                    "app_id": "mail-readwrite",
                    "access_class": "write-capable",
                    "auth_url": "https://oauth.yandex.ru/other",
                    "is_default": False,
                },
            )(),
        ]

    def fake_save(path: Path, token_data: dict) -> None:
        saved["path"] = path
        saved["token_data"] = token_data

    def fake_load(_path: Path) -> dict:
        raise FileNotFoundError

    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", fake_bootstrap)
    monkeypatch.setattr(oauth_setup, "plan_oauth_setup", fake_plan)
    monkeypatch.setattr(oauth_setup, "list_service_profiles", fake_profiles)
    monkeypatch.setattr(oauth_setup, "save_token_file", fake_save)
    monkeypatch.setattr(oauth_setup, "load_token_file", fake_load)
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "token-value")
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
            "--service",
            "mail",
        ],
    )

    oauth_setup.main()

    assert calls["account"] == "work"
    assert calls["email"] == "work@example.com"
    assert calls["cwd"] == workspace.resolve()
    assert calls["data_dir_override"] is None
    assert saved["path"] == data_dir / "auth" / "work.token"
    token_data = saved["token_data"]
    assert token_data["email"] == "work@example.com"
    assert token_data["token.mail"] == "token-value"
    assert token_data["token_meta"]["token.mail"]["app_id"] == "mail-readonly"


def test_oauth_setup_without_args_bootstraps_only(monkeypatch, tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_dir = workspace / "yandex-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.json",
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
    monkeypatch.setattr(oauth_setup, "plan_oauth_setup", fail)
    monkeypatch.setattr(oauth_setup, "save_token_file", fail)
    monkeypatch.setattr(oauth_setup, "load_token_file", fail)
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(sys, "argv", ["oauth_setup.py"])

    oauth_setup.main()

    captured = capsys.readouterr()
    assert calls["account"] is None
    assert calls["email"] is None
    assert calls["cwd"] == workspace.resolve()
    assert calls["data_dir_override"] is None
    assert "Yandex bootstrap complete" in captured.out
    assert str(data_dir.resolve()) in captured.out


def test_oauth_setup_adds_account_without_service(monkeypatch, tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_dir = workspace / "yandex-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.json",
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

    def fail(*_args, **_kwargs):
        raise AssertionError("OAuth planning/saving should not run in add-account mode")

    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", fake_bootstrap)
    monkeypatch.setattr(oauth_setup, "plan_oauth_setup", fail)
    monkeypatch.setattr(oauth_setup, "save_token_file", fail)
    monkeypatch.setattr(oauth_setup, "load_token_file", fail)
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
    assert "Yandex account added" in captured.out
    assert "Account:  alex" in captured.out


def test_oauth_setup_rejects_partial_identity_args(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(
        sys,
        "argv",
        ["oauth_setup.py", "--account", "work"],
    )

    try:
        oauth_setup.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected argparse failure for partial identity args")


def test_oauth_setup_rejects_service_without_identity(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(
        sys,
        "argv",
        ["oauth_setup.py", "--service", "mail"],
    )

    try:
        oauth_setup.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected argparse failure for service without identity args")


def test_oauth_setup_prints_default_and_other_profiles(
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
        global_config_path=ROOT_DIR / "config.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=data_dir / "config.agent.json",
        agent_config={"accounts": [{"name": "alex", "email": "user@example.com"}]},
        config={"accounts": [{"name": "alex", "email": "user@example.com"}]},
    )

    def fake_bootstrap(
        start_path: str | Path,
        *,
        account: str,
        email: str,
        cwd: str | Path | None = None,
        data_dir_override: str | Path | None = None,
    ) -> RuntimeContext:
        return runtime

    def fake_plan(config, *, service, app_id=None, client_id=None, extra_scopes=None):
        return OAuthSetupPlan(
            service=service,
            client_id="client-id",
            scopes=["cloud_api:disk.read"],
            auth_url="https://oauth.yandex.ru/default",
            mode="configured_app",
            include_scope_in_url=False,
            app_id="disk-read",
            app_name="Disk Read",
        )

    def fake_profiles(_config, _service):
        return [
            type(
                "Profile",
                (),
                {
                    "app_id": "disk-read",
                    "access_class": "read-only",
                    "auth_url": "https://oauth.yandex.ru/default",
                    "is_default": True,
                },
            )(),
            type(
                "Profile",
                (),
                {
                    "app_id": "disk-full",
                    "access_class": "write-capable",
                    "auth_url": "https://oauth.yandex.ru/full",
                    "is_default": False,
                },
            )(),
        ]

    monkeypatch.setattr(oauth_setup, "bootstrap_runtime_context", fake_bootstrap)
    monkeypatch.setattr(oauth_setup, "plan_oauth_setup", fake_plan)
    monkeypatch.setattr(oauth_setup, "list_service_profiles", fake_profiles)
    monkeypatch.setattr(oauth_setup, "save_token_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(oauth_setup, "load_token_file", lambda _path: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "token-value")
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "oauth_setup.py",
            "--email",
            "user@example.com",
            "--account",
            "alex",
            "--service",
            "disk",
        ],
    )

    oauth_setup.main()

    captured = capsys.readouterr()
    assert "Default profile:" in captured.out
    assert "disk-read" in captured.out
    assert "read-only" in captured.out
    assert "Other profiles:" in captured.out
    assert "disk-full" in captured.out
    assert "write-capable" in captured.out
    assert "--app <profile_id>" in captured.out


def test_oauth_setup_uses_data_dir_parent_as_bootstrap_cwd(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    data_dir = workspace / "custom-yandex"
    data_dir.mkdir(parents=True, exist_ok=True)

    runtime = RuntimeContext(
        skill_root=ROOT_DIR,
        cwd=workspace.resolve(),
        global_config_path=ROOT_DIR / "config.json",
        global_config={},
        data_dir=data_dir.resolve(),
        agent_config_path=data_dir / "config.agent.json",
        agent_config={"accounts": [{"name": "work", "email": "work@example.com"}]},
        config={"accounts": [{"name": "work", "email": "work@example.com"}]},
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
        oauth_setup,
        "plan_oauth_setup",
        lambda *_args, **_kwargs: OAuthSetupPlan(
            service="mail",
            client_id="client-id",
            scopes=["mail:imap_ro"],
            auth_url="https://oauth.yandex.ru/authorize?response_type=token&client_id=client-id",
            mode="configured_app",
            include_scope_in_url=False,
            app_id="mail-readonly",
            app_name="OpenClaw Yandex Mail Readonly",
        ),
    )
    monkeypatch.setattr(oauth_setup, "save_token_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(oauth_setup, "load_token_file", lambda _path: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "token-value")
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
            "--service",
            "mail",
            "--data-dir",
            str(data_dir),
        ],
    )

    oauth_setup.main()

    assert calls["cwd"] == ROOT_DIR.resolve()
    assert calls["data_dir_override"] == data_dir.resolve()


def test_list_service_profiles_ignores_other_services() -> None:
    config = {
        "oauth_apps": {
            "service_defaults": {
                "disk": "disk-read",
                "calendar": "calendar-user",
            },
            "catalog": {
                "calendar-user": {
                    "service": "calendar",
                    "client_id": "calendar-client",
                    "scopes": ["calendar:all"],
                },
                "disk-read": {
                    "service": "disk",
                    "client_id": "disk-read-client",
                    "scopes": ["cloud_api:disk.read"],
                },
                "disk-full": {
                    "service": "disk",
                    "client_id": "disk-full-client",
                    "scopes": ["cloud_api:disk.read", "cloud_api:disk.write"],
                },
            },
        }
    }

    profiles = list_service_profiles(config, "disk")

    assert [profile.app_id for profile in profiles] == ["disk-read", "disk-full"]
    assert profiles[0].is_default is True
    assert profiles[0].access_class == "read-only"
    assert profiles[1].access_class == "write-capable"
