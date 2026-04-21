"""Shared configuration loader for all Yandex sub-skills."""

from __future__ import annotations

import json
from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any


GLOBAL_CONFIG_NAME = "config.skill.json"
LEGACY_GLOBAL_CONFIG_NAME = "config.json"
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


def _normalized_accounts(payload: dict[str, Any]) -> tuple[list[dict[str, str]], bool]:
    accounts_raw = payload.get("accounts")
    if accounts_raw is None:
        accounts_raw = payload.get("mailboxes")
    raw_items = accounts_raw if isinstance(accounts_raw, list) else []
    accounts: list[dict[str, str]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        email = str(item.get("email", "")).strip()
        if not name or not email:
            continue
        normalized = dict(item)
        normalized["name"] = name
        normalized["email"] = email
        accounts.append(normalized)
    updated = "mailboxes" in payload or payload.get("accounts") != accounts
    return accounts, updated


def list_accounts(payload: dict[str, Any]) -> list[dict[str, str]]:
    accounts, _ = _normalized_accounts(payload)
    return accounts


def find_account_by_email(payload: dict[str, Any], email: str) -> dict[str, str] | None:
    normalized_email = str(email).strip().lower()
    if not normalized_email:
        return None
    for account in list_accounts(payload):
        if str(account.get("email", "")).strip().lower() == normalized_email:
            return account
    return None


def _suggest_account_name(email: str, preferred_name: str | None = None) -> str:
    preferred = str(preferred_name or "").strip()
    if preferred:
        return preferred
    local_part = str(email).split("@", 1)[0].strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", local_part).strip("-")
    return slug or "account"


def ensure_account(
    agent_config_path: str | Path,
    *,
    email: str,
    preferred_name: str | None = None,
) -> dict[str, str]:
    path = Path(agent_config_path).resolve()
    payload = _read_json(path) if path.exists() else {}
    accounts, updated = _normalized_accounts(payload)
    normalized_email = str(email).strip()
    existing = find_account_by_email(payload, normalized_email)
    if existing is not None:
        if updated:
            payload["accounts"] = accounts
            payload.pop("mailboxes", None)
            _write_json(path, payload)
        return existing

    used_names = {str(account.get("name", "")).strip() for account in accounts}
    base_name = _suggest_account_name(normalized_email, preferred_name)
    resolved_name = base_name
    suffix = 2
    while resolved_name in used_names:
        resolved_name = f"{base_name}-{suffix}"
        suffix += 1

    entry = {"name": resolved_name, "email": normalized_email}
    accounts.append(entry)
    payload["accounts"] = accounts
    payload.pop("mailboxes", None)
    _write_json(path, payload)
    return entry


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
        legacy_config_path = candidate / LEGACY_GLOBAL_CONFIG_NAME
        if config_path.exists() or legacy_config_path.exists():
            return candidate

    raise FileNotFoundError(
        f"{GLOBAL_CONFIG_NAME} or {LEGACY_GLOBAL_CONFIG_NAME} not found above "
        f"{Path(start_path).resolve()}"
    )


def load_global_config(
    skill_root: str | Path,
    *,
    bootstrap: bool = False,
) -> tuple[Path, dict[str, Any]]:
    del bootstrap
    root = Path(skill_root).resolve()
    config_path = root / GLOBAL_CONFIG_NAME
    if config_path.exists():
        return config_path, _read_json(config_path)

    legacy_config_path = root / LEGACY_GLOBAL_CONFIG_NAME
    if legacy_config_path.exists():
        return legacy_config_path, _read_json(legacy_config_path)

    raise FileNotFoundError(
        f"Global config not found: expected {config_path} "
        f"(or legacy compatibility file {legacy_config_path})."
    )


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

    accounts, updated = _normalized_accounts(payload)
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
        payload["accounts"] = list_accounts(payload)
        payload.pop("mailboxes", None)
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
