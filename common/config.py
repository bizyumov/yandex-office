"""Shared configuration loader for all Yandex sub-skills."""

from __future__ import annotations

import json
from dataclasses import dataclass
import re
from pathlib import Path
import sys
from typing import Any


GLOBAL_CONFIG_NAME = "config.skill.json"
LEGACY_GLOBAL_CONFIG_NAME = "config.json"
AGENT_CONFIG_NAME = "config.agent.json"
AGENT_CONFIG_TEMPLATE_NAME = "config.agent.example.json"
DEFAULT_DATA_DIR = "yandex-data"


def _read_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def find_skill_root(start_path: str | Path) -> Path:
    current = Path(start_path).resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / GLOBAL_CONFIG_NAME).exists() or (candidate / LEGACY_GLOBAL_CONFIG_NAME).exists():
            return candidate
    raise FileNotFoundError(
        f"{GLOBAL_CONFIG_NAME} or {LEGACY_GLOBAL_CONFIG_NAME} not found above "
        f"{Path(start_path).resolve()}"
    )


def load_global_config(skill_root: str | Path, *, bootstrap: bool = False) -> tuple[Path, dict[str, Any]]:
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


def resolve_data_dir(cwd: str | Path | None = None, data_dir_override: str | Path | None = None) -> Path:
    global data_dir, LEGACY_AUTH_PATH
    if data_dir_override is not None:
        resolved = Path(data_dir_override).resolve()
    else:
        base_dir = Path.cwd() if cwd is None else Path(cwd).resolve()
        resolved = (base_dir / DEFAULT_DATA_DIR).resolve()
    data_dir = resolved
    LEGACY_AUTH_PATH = resolved / "auth"
    return resolved


config = load_global_config(find_skill_root(__file__))[1]
config["data_dir"] = str(resolve_data_dir())

data_dir = Path(config["data_dir"])
AUTH_PATH = Path("~/secrets/yandex-office")
LEGACY_AUTH_PATH = data_dir / "auth"


LEGACY_AUTH_MIGRATION_WARNING = (
    "WARNING: Legacy Yandex Office credentials were found and successfully moved "
    "to ~/secrets/yandex-office."
)


def _ensure_auth_path() -> Path:
    """Create the canonical secret directory with owner-only permissions."""
    auth_path = AUTH_PATH.expanduser()
    auth_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    auth_path.chmod(0o700)
    return auth_path


def resolve_auth_file(filename: str) -> Path:
    """Resolve a canonical secret file and migrate its legacy counterpart once."""
    safe_name = str(filename).strip()
    if not safe_name or Path(safe_name).name != safe_name:
        raise ValueError("Auth filename must be a plain filename")

    canonical_path = _ensure_auth_path() / safe_name
    if canonical_path.exists():
        return canonical_path

    legacy_path = LEGACY_AUTH_PATH / safe_name
    if not legacy_path.exists():
        return canonical_path

    legacy_path.chmod(0o600)
    legacy_path.replace(canonical_path)
    print(LEGACY_AUTH_MIGRATION_WARNING, file=sys.stderr)
    return canonical_path


def list_auth_token_paths() -> list[Path]:
    """Return canonical token paths after migrating missing legacy counterparts."""
    canonical_dir = _ensure_auth_path()
    if LEGACY_AUTH_PATH.exists():
        for legacy_path in sorted(LEGACY_AUTH_PATH.glob("*.token")):
            resolve_auth_file(legacy_path.name)
    return sorted(canonical_dir.glob("*.token"))


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
        """Return a path inside the resolved runtime data directory."""
        return self.data_dir.joinpath(*parts)

    def auth_file(self, account: str) -> Path:
        """Return the token file path for an account alias."""
        return resolve_auth_file(f"{account}.token")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON object to disk with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def list_token_accounts() -> list[dict[str, Any]]:
    """Return account rows derived from managed auth token files."""
    accounts: list[dict[str, Any]] = []
    for token_path in list_auth_token_paths():
        try:
            payload = _read_json(token_path)
        except json.JSONDecodeError:
            continue
        email = str(payload.get("email", "")).strip()
        if not email:
            continue
        tokens: dict[str, str] = {}
        for key, value in payload.items():
            if key == "email":
                continue
            if key.startswith("token."):
                continue
            if isinstance(value, dict):
                client_id = str(value.get("client_id", "")).strip()
                if client_id:
                    tokens[str(key)] = client_id
            elif isinstance(value, str):
                # Legacy transitional read for pre-runtime-state token files.
                tokens[str(key)] = value
        accounts.append(
            {
                "name": token_path.stem,
                "alias": token_path.stem,
                "email": email,
                "token_path": str(token_path),
                "tokens": tokens,
            }
        )
    return accounts


def yandex_identity_matches(left: str, right: str) -> bool:
    """Return whether two values describe the same Yandex login identity."""
    left_value = str(left).strip().lower()
    right_value = str(right).strip().lower()
    if not left_value or not right_value:
        return False
    return (
        left_value == right_value
        or ("@" not in left_value and right_value == f"{left_value}@yandex.ru")
        or ("@" not in right_value and left_value == f"{right_value}@yandex.ru")
    )


def find_token_account_by_email(email: str) -> dict[str, Any] | None:
    """Find a token-backed account by verified Yandex identity."""
    if not str(email).strip():
        return None
    for account in list_token_accounts():
        if yandex_identity_matches(str(account.get("email", "")), email):
            return account
    return None


def _suggest_account_name(email: str, preferred_name: str | None = None) -> str:
    """Suggest a stable account alias from an email or preferred name."""
    preferred = str(preferred_name or "").strip()
    if preferred:
        return preferred
    local_part = str(email).split("@", 1)[0].strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", local_part).strip("-")
    return slug or "account"


def choose_account_alias(
    email: str,
    preferred_name: str | None = None,
) -> str:
    """Choose an unused token-file alias for an email address."""
    used_names = {path.stem for path in list_auth_token_paths()}
    base_name = _suggest_account_name(email, preferred_name)
    resolved_name = base_name
    suffix = 2
    while resolved_name in used_names:
        resolved_name = f"{base_name}-{suffix}"
        suffix += 1
    return resolved_name


def _deep_merge(base: Any, override: Any) -> Any:
    """Recursively merge override values into a base config object."""
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
    return override


def _ensure_external_data_dir(skill_root: Path, data_dir: Path) -> None:
    """Reject data directories inside the shared skill tree."""
    if data_dir == skill_root or skill_root in data_dir.parents:
        raise RuntimeError(
            "Resolved data_dir points inside the shared skill tree. "
            "Run from CWD or pass --data-dir explicitly."
        )


def _bootstrap_agent_config(
    skill_root: Path,
    agent_config_path: Path,
) -> None:
    """Create or normalize the agent config file in the data directory."""
    if agent_config_path.exists():
        payload = _read_json(agent_config_path)
    else:
        template_path = skill_root / AGENT_CONFIG_TEMPLATE_NAME
        payload = _read_json(template_path) if template_path.exists() else {}
        if payload.get("accounts") == []:
            payload.pop("accounts", None)

    if not agent_config_path.exists():
        _write_json(agent_config_path, payload)


def bootstrap_runtime_context(
    start_path: str | Path,
    *,
    account: str | None = None,
    email: str | None = None,
    cwd: str | Path | None = None,
    data_dir_override: str | Path | None = None,
) -> RuntimeContext:
    """Bootstrap runtime data directories and return a runtime context."""
    skill_root = find_skill_root(start_path)
    actual_cwd = Path.cwd() if cwd is None else Path(cwd).resolve()
    _, global_config = load_global_config(skill_root, bootstrap=True)
    data_dir = resolve_data_dir(cwd=actual_cwd, data_dir_override=data_dir_override)
    _ensure_external_data_dir(skill_root, data_dir)

    data_dir.mkdir(parents=True, exist_ok=True)
    for name in ("incoming", "meetings"):
        (data_dir / name).mkdir(parents=True, exist_ok=True)

    agent_config_path = data_dir / AGENT_CONFIG_NAME
    _bootstrap_agent_config(skill_root, agent_config_path)

    return load_runtime_context(
        start_path,
        cwd=actual_cwd,
        data_dir_override=data_dir,
        require_agent_config=True,
        require_external_data_dir=True,
    )


def load_agent_config(
    data_dir_path: str | Path,
    *,
    required: bool = False,
) -> tuple[Path, dict[str, Any]]:
    """Load and normalize the agent config payload for a data directory."""
    resolve_data_dir(data_dir_override=data_dir_path)
    data_path = Path(data_dir_path).resolve()
    agent_config_path = data_path / AGENT_CONFIG_NAME
    if agent_config_path.exists():
        payload = _read_json(agent_config_path)
        token_accounts = list_token_accounts()
        if token_accounts:
            payload["accounts"] = [
                {"name": item["alias"], "email": item["email"]}
                for item in token_accounts
            ]
        else:
            payload["accounts"] = []
        return agent_config_path, payload
    if required:
        raise FileNotFoundError(
            f"Agent config not found: {agent_config_path}. "
            "Onboarding is not complete or the resolved data_dir is wrong. "
            "Run python3 <full-path-to-yandex-office>/scripts/oauth_setup.py from CWD "
            "or pass --data-dir explicitly."
        )
    return agent_config_path, {}


def load_agent_config_payload(data_dir_path: str | Path) -> tuple[Path, dict[str, Any]]:
    """Load the raw agent config payload without token-derived account overlay."""
    data_path = Path(data_dir_path).resolve()
    agent_config_path = data_path / AGENT_CONFIG_NAME
    if agent_config_path.exists():
        return agent_config_path, _read_json(agent_config_path)
    return agent_config_path, {}


def save_agent_config_payload(agent_config_path: str | Path, payload: dict[str, Any]) -> None:
    """Save an agent config payload to disk."""
    _write_json(Path(agent_config_path).resolve(), payload)


def load_runtime_context(
    start_path: str | Path,
    *,
    cwd: str | Path | None = None,
    data_dir_override: str | Path | None = None,
    require_agent_config: bool = False,
    require_external_data_dir: bool = False,
) -> RuntimeContext:
    """Load merged shared and agent configuration for a sub-skill."""
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
