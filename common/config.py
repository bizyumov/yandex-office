"""Shared configuration loader for all Yandex sub-skills."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GLOBAL_CONFIG_NAME = "config.json"
AGENT_CONFIG_NAME = "config.agent.json"
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
        if config_path.exists():
            return candidate

    raise FileNotFoundError(
        f"{GLOBAL_CONFIG_NAME} not found above {Path(start_path).resolve()}"
    )


def load_global_config(skill_root: str | Path) -> tuple[Path, dict[str, Any]]:
    root = Path(skill_root).resolve()
    config_path = root / GLOBAL_CONFIG_NAME
    if not config_path.exists():
        raise FileNotFoundError(f"Global config not found: {config_path}")
    return config_path, _read_json(config_path)


def resolve_data_dir(
    global_config: dict[str, Any],
    cwd: str | Path | None = None,
) -> Path:
    base_dir = Path.cwd() if cwd is None else Path(cwd).resolve()
    raw_data_dir = global_config.get("data_dir", DEFAULT_DATA_DIR)
    data_dir = Path(raw_data_dir)
    if not data_dir.is_absolute():
        data_dir = base_dir / data_dir
    return data_dir.resolve()


def load_agent_config(
    data_dir: str | Path,
    *,
    required: bool = False,
) -> tuple[Path, dict[str, Any]]:
    data_path = Path(data_dir).resolve()
    agent_config_path = data_path / AGENT_CONFIG_NAME
    if agent_config_path.exists():
        return agent_config_path, _read_json(agent_config_path)
    if required:
        raise FileNotFoundError(f"Agent config not found: {agent_config_path}")
    return agent_config_path, {}


def load_runtime_context(
    start_path: str | Path,
    *,
    cwd: str | Path | None = None,
    require_agent_config: bool = False,
) -> RuntimeContext:
    skill_root = find_skill_root(start_path)
    global_config_path, global_config = load_global_config(skill_root)
    actual_cwd = Path.cwd() if cwd is None else Path(cwd).resolve()
    data_dir = resolve_data_dir(global_config, cwd=actual_cwd)
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

