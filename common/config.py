"""Shared configuration loader for all Yandex sub-skills."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any


GLOBAL_CONFIG_NAME = "config.json"
GLOBAL_CONFIG_TEMPLATE_NAME = "config.example.json"
AGENT_CONFIG_NAME = "config.agent.json"
AGENT_CONFIG_TEMPLATE_NAME = "config.agent.example.json"
DEFAULT_DATA_DIR = "yandex-data"


@dataclass(frozen=True)
class RuntimeContext:
    """Resolved runtime context for a Yandex sub-skill."""

    skill_root: Path
    cwd: Path
    global_config_path: Path
    global_config: dict[str, Any]
    data_dir: Path
    agent_config_path: Path
    agent_config: dict[str, Any]
    config: dict[str, Any]

    def path(self, *parts: str) -> Path:
        return self.data_dir.joinpath(*parts)

    def auth_file(self, account: str) -> Path:
        return self.path("auth", f"{account}.token")


def _read_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
    return override


def find_skill_root(start_path: str | Path) -> Path:
    current = Path(start_path).resolve()
    if current.is_file():
        current = current.parent

    for candidate in [current] + list(current.parents):
        config_path = candidate / GLOBAL_CONFIG_NAME
        template_path = candidate / GLOBAL_CONFIG_TEMPLATE_NAME
        if config_path.exists() or template_path.exists():
            return candidate

    raise FileNotFoundError(
        f"{GLOBAL_CONFIG_NAME} or {GLOBAL_CONFIG_TEMPLATE_NAME} not found above "
        f"{Path(start_path).resolve()}"
    )


def load_global_config(
    skill_root: str | Path,
    *,
    bootstrap: bool = False,
) -> tuple[Path, dict[str, Any]]:
    root = Path(skill_root).resolve()
    config_path = root / GLOBAL_CONFIG_NAME
    if config_path.exists():
        return config_path, _read_json(config_path)

    template_path = root / GLOBAL_CONFIG_TEMPLATE_NAME
    if bootstrap and template_path.exists():
        shutil.copyfile(template_path, config_path)
        return config_path, _read_json(config_path)

    if template_path.exists():
        raise FileNotFoundError(
            f"Global config not found: {config_path}. Run onboarding first to create "
            f"{GLOBAL_CONFIG_NAME} from {GLOBAL_CONFIG_TEMPLATE_NAME}."
        )

    raise FileNotFoundError(f"Global config not found: {config_path}")


def _ensure_external_data_dir(skill_root: Path, data_dir: Path) -> None:
    if data_dir == skill_root or skill_root in data_dir.parents:
        raise RuntimeError(
            "Resolved data_dir points inside the shared skill tree. "
            "Run from the agent workspace CWD or pass --data-dir explicitly."
        )


def _bootstrap_agent_config(
    skill_root: Path,
    agent_config_path: Path,
    *,
    account: str | None = None,
    email: str | None = None,
) -> None:
    if agent_config_path.exists():
        payload = _read_json(agent_config_path)
    else:
        template_path = skill_root / AGENT_CONFIG_TEMPLATE_NAME
        payload = _read_json(template_path) if template_path.exists() else {}

    accounts_raw = payload.get("accounts")
    if accounts_raw is None:
        accounts_raw = payload.get("mailboxes")
    accounts = list(accounts_raw) if isinstance(accounts_raw, list) else []
    updated = False
    if account is not None and email is not None:
        for account_entry in accounts:
            if account_entry.get("name") == account:
                if account_entry.get("email") != email:
                    account_entry["email"] = email
                    updated = True
                break
        else:
            accounts.append({"name": account, "email": email})
            updated = True

    if "mailboxes" in payload:
        payload.pop("mailboxes", None)
        updated = True

    if "accounts" not in payload:
        updated = True

    if not agent_config_path.exists() or updated:
        payload["accounts"] = accounts
        _write_json(agent_config_path, payload)


def bootstrap_runtime_context(
    start_path: str | Path,
    *,
    account: str | None = None,
    email: str | None = None,
    cwd: str | Path | None = None,
    data_dir_override: str | Path | None = None,
) -> RuntimeContext:
    skill_root = find_skill_root(start_path)
    actual_cwd = Path.cwd() if cwd is None else Path(cwd).resolve()
    _, global_config = load_global_config(skill_root, bootstrap=True)
    data_dir = resolve_data_dir(cwd=actual_cwd, data_dir_override=data_dir_override)
    _ensure_external_data_dir(skill_root, data_dir)

    data_dir.mkdir(parents=True, exist_ok=True)
    for name in ("auth", "incoming", "meetings"):
        (data_dir / name).mkdir(parents=True, exist_ok=True)

    agent_config_path = data_dir / AGENT_CONFIG_NAME
    _bootstrap_agent_config(
        skill_root,
        agent_config_path,
        account=account,
        email=email,
    )

    return load_runtime_context(
        start_path,
        cwd=actual_cwd,
        data_dir_override=data_dir,
        require_agent_config=True,
        require_external_data_dir=True,
    )


def resolve_data_dir(
    cwd: str | Path | None = None,
    data_dir_override: str | Path | None = None,
) -> Path:
    if data_dir_override is not None:
        return Path(data_dir_override).resolve()
    base_dir = Path.cwd() if cwd is None else Path(cwd).resolve()
    return (base_dir / DEFAULT_DATA_DIR).resolve()


def load_agent_config(
    data_dir: str | Path,
    *,
    required: bool = False,
) -> tuple[Path, dict[str, Any]]:
    data_path = Path(data_dir).resolve()
    agent_config_path = data_path / AGENT_CONFIG_NAME
    if agent_config_path.exists():
        payload = _read_json(agent_config_path)
        if "accounts" not in payload and "mailboxes" in payload:
            payload["accounts"] = payload["mailboxes"]
        return agent_config_path, payload
    if required:
        raise FileNotFoundError(
            f"Agent config not found: {agent_config_path}. "
            "Onboarding is not complete or the resolved data_dir is wrong. "
            "Run scripts/oauth_setup.py by full path from the agent workspace CWD "
            "or pass --data-dir explicitly."
        )
    return agent_config_path, {}


def load_runtime_context(
    start_path: str | Path,
    *,
    cwd: str | Path | None = None,
    data_dir_override: str | Path | None = None,
    require_agent_config: bool = False,
    require_external_data_dir: bool = False,
) -> RuntimeContext:
    skill_root = find_skill_root(start_path)
    global_config_path, global_config = load_global_config(skill_root)
    actual_cwd = Path.cwd() if cwd is None else Path(cwd).resolve()
    data_dir = resolve_data_dir(cwd=actual_cwd, data_dir_override=data_dir_override)
    if require_external_data_dir:
        _ensure_external_data_dir(skill_root, data_dir)
    agent_config_path, agent_config = load_agent_config(
        data_dir,
        required=require_agent_config,
    )
    merged = _deep_merge(global_config, agent_config)
    merged["data_dir"] = str(data_dir)
    return RuntimeContext(
        skill_root=skill_root,
        cwd=actual_cwd,
        global_config_path=global_config_path,
        global_config=global_config,
        data_dir=data_dir,
        agent_config_path=agent_config_path,
        agent_config=agent_config,
        config=merged,
    )
