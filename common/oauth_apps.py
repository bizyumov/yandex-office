"""Shared planning logic for Yandex OAuth token setup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from common.auth import build_approval_url


@dataclass(frozen=True)
class OAuthAppConfig:
    service: str
    client_id: str
    scopes: list[str]
    app_id: str
    app_name: str | None = None
    omit_scope_in_url: bool = True
    services: tuple[str, ...] = ()


@dataclass(frozen=True)
class OAuthSetupPlan:
    service: str
    client_id: str
    scopes: list[str]
    auth_url: str
    mode: str
    include_scope_in_url: bool
    app_id: str | None = None
    app_name: str | None = None


@dataclass(frozen=True)
class OAuthProfileOption:
    service: str
    app_id: str
    app_name: str | None
    scopes: list[str]
    auth_url: str
    access_class: str
    is_default: bool


def _clean_scopes(scopes: list[str] | None) -> list[str]:
    cleaned = [str(scope).strip() for scope in scopes or [] if str(scope).strip()]
    return sorted(set(cleaned))


def _clean_services(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    return sorted(set(str(item).strip() for item in raw_items if str(item).strip()))


def _oauth_apps_root(config: dict[str, Any]) -> dict[str, Any]:
    apps = config.get("oauth_apps")
    return apps if isinstance(apps, dict) else {}


def _oauth_catalog(config: dict[str, Any]) -> dict[str, Any]:
    catalog = _oauth_apps_root(config).get("catalog")
    return catalog if isinstance(catalog, dict) else {}


def _catalog_entries_for_service(config: dict[str, Any], service: str) -> list[tuple[str, dict[str, Any]]]:
    entries: list[tuple[str, dict[str, Any]]] = []
    for app_id, raw in sorted(_oauth_catalog(config).items()):
        if not isinstance(raw, dict):
            continue
        if service in _clean_services(raw.get("service")):
            entries.append((app_id, raw))
    return entries


def supported_services(config: dict[str, Any]) -> list[str]:
    services = {"auth"}
    for _app_id, raw in _oauth_catalog(config).items():
        if not isinstance(raw, dict):
            continue
        services.update(_clean_services(raw.get("service")))
    return sorted(services)


def _is_default_app(raw: dict[str, Any]) -> bool:
    return bool(raw.get("is_default", False))


def _classify_catalog_entry(raw: dict[str, Any]) -> str:
    return classify_access(_clean_scopes(raw.get("scopes")))


def _resolve_service_app_id(config: dict[str, Any], service: str, *, mode: str = "default") -> str | None:
    entries = _catalog_entries_for_service(config, service)
    if not entries:
        return None

    default_entries = [(app_id, raw) for app_id, raw in entries if _is_default_app(raw)]
    default_app_id = default_entries[0][0] if default_entries else None
    if mode == "default":
        return default_app_id or entries[0][0]

    if mode == "read":
        if default_app_id is not None:
            return default_app_id
        return entries[0][0]

    if mode == "write":
        for app_id, raw in entries:
            access_class = _classify_catalog_entry(raw)
            if access_class in {"write-capable", "full access"}:
                return app_id
        return default_app_id or entries[0][0]

    return default_app_id or entries[0][0]


def default_service_scopes(
    config: dict[str, Any],
    service: str,
    mode: str = "default",
) -> list[str]:
    app_id = _resolve_service_app_id(config, service, mode=mode)
    if not app_id:
        return []
    raw = _oauth_catalog(config).get(app_id)
    if not isinstance(raw, dict):
        return []
    if service not in _clean_services(raw.get("service")):
        return []
    return _clean_scopes(raw.get("scopes"))


def configured_oauth_app(
    config: dict[str, Any],
    service: str,
    app_id: str | None = None,
    *,
    mode: str = "default",
) -> OAuthAppConfig | None:
    catalog = _oauth_catalog(config)
    resolved_app_id = str(app_id or _resolve_service_app_id(config, service, mode=mode) or "").strip()
    if not resolved_app_id:
        return None

    raw = catalog.get(resolved_app_id)
    if not isinstance(raw, dict):
        return None

    configured_services = _clean_services(raw.get("service"))
    if service not in configured_services:
        raise ValueError(
            f"OAuth app '{resolved_app_id}' is configured for service "
            f"'{', '.join(configured_services) or '(missing)'}', not '{service}'"
        )

    client_id = str(raw.get("client_id", "")).strip()
    if not client_id:
        return None

    app_name = str(raw.get("app_name", "")).strip() or None
    scopes = _clean_scopes(raw.get("scopes"))

    omit_scope_in_url = raw.get("omit_scope_in_url", True)
    return OAuthAppConfig(
        service=service,
        client_id=client_id,
        scopes=scopes,
        app_id=resolved_app_id,
        app_name=app_name,
        omit_scope_in_url=bool(omit_scope_in_url),
        services=tuple(configured_services),
    )


def configured_oauth_app_by_id(config: dict[str, Any], app_id: str) -> OAuthAppConfig | None:
    resolved_app_id = str(app_id).strip()
    if not resolved_app_id:
        return None
    raw = _oauth_catalog(config).get(resolved_app_id)
    if not isinstance(raw, dict):
        return None
    configured_services = _clean_services(raw.get("service"))
    if not configured_services:
        return None
    return configured_oauth_app(config, configured_services[0], resolved_app_id)


def classify_access(scopes: list[str]) -> str:
    normalized = [str(scope).strip().lower() for scope in scopes if str(scope).strip()]
    if not normalized:
        return "custom"
    if any(scope.endswith(":all") for scope in normalized):
        return "full access"

    write_markers = ("write", "delete", "update", "create", "manage", "full")
    if any(any(marker in scope for marker in write_markers) for scope in normalized):
        return "write-capable"
    return "read-only"


def list_service_profiles(config: dict[str, Any], service: str) -> list[OAuthProfileOption]:
    entries = _catalog_entries_for_service(config, service)
    default_app_id = _resolve_service_app_id(config, service, mode="default")
    options: list[OAuthProfileOption] = []
    for app_id, _raw in entries:
        app = configured_oauth_app(config, service, app_id)
        if app is None:
            continue
        include_scope = not app.omit_scope_in_url
        auth_url = build_approval_url(
            config,
            client_id=app.client_id,
            scopes=app.scopes,
            include_scope=include_scope,
        )
        options.append(
            OAuthProfileOption(
                service=service,
                app_id=app.app_id,
                app_name=app.app_name,
                scopes=app.scopes,
                auth_url=auth_url,
                access_class=classify_access(app.scopes),
                is_default=app.app_id == default_app_id,
            )
        )

    options.sort(key=lambda option: (not option.is_default, option.app_id))
    return options


def oauth_app_for_client_id(
    config: dict[str, Any],
    client_id: str,
    *,
    service: str | None = None,
) -> OAuthAppConfig | None:
    normalized_client_id = str(client_id).strip()
    if not normalized_client_id:
        return None

    catalog = _oauth_catalog(config)

    for app_id in sorted(catalog):
        raw = catalog.get(app_id)
        if not isinstance(raw, dict):
            continue
        configured_services = _clean_services(raw.get("service"))
        if service is not None and service not in configured_services:
            continue
        if str(raw.get("client_id", "")).strip() != normalized_client_id:
            continue
        if not configured_services:
            continue
        return configured_oauth_app(config, service or configured_services[0], app_id)
    return None


def plan_oauth_setup(
    config: dict[str, Any],
    *,
    service: str,
    app_id: str | None = None,
    client_id: str | None = None,
    extra_scopes: list[str] | None = None,
) -> OAuthSetupPlan:
    if service not in supported_services(config):
        raise ValueError(f"Unsupported service: {service}")

    explicit_client_id = (client_id or "").strip()
    explicit_scopes = _clean_scopes(extra_scopes)

    if service == "auth":
        if app_id:
            raise ValueError("--service auth does not support --app")
        if not explicit_client_id:
            raise ValueError("--service auth requires --client-id")
        if not explicit_scopes:
            raise ValueError("--service auth requires at least one --scope")
        auth_url = build_approval_url(
            config,
            client_id=explicit_client_id,
            scopes=explicit_scopes,
            include_scope=True,
        )
        return OAuthSetupPlan(
            service=service,
            client_id=explicit_client_id,
            scopes=explicit_scopes,
            auth_url=auth_url,
            mode="explicit",
            include_scope_in_url=True,
        )

    if not explicit_client_id and explicit_scopes:
        raise ValueError("--scope overrides require --client-id")

    if explicit_client_id:
        if app_id:
            raise ValueError("--app cannot be combined with --client-id")
        scopes = explicit_scopes or default_service_scopes(config, service, "default")
        auth_url = build_approval_url(
            config,
            client_id=explicit_client_id,
            scopes=scopes,
            include_scope=True,
        )
        return OAuthSetupPlan(
            service=service,
            client_id=explicit_client_id,
            scopes=scopes,
            auth_url=auth_url,
            mode="explicit",
            include_scope_in_url=True,
        )

    app = configured_oauth_app(config, service, app_id)
    if app is None:
        raise ValueError(
            f"No configured OAuth app for service '{service}'. "
            "Add oauth_apps.catalog.<app_id> entries with matching service and one is_default app in config.skill.json, "
            "or pass --client-id for an advanced one-off override."
        )
    if not app.scopes:
        raise ValueError(
            f"Configured OAuth app for service '{service}' has no scopes. "
            "Set oauth_apps.catalog.<app_id>.scopes or use explicit --scope values with --client-id."
        )

    include_scope = not app.omit_scope_in_url
    auth_url = build_approval_url(
        config,
        client_id=app.client_id,
        scopes=app.scopes,
        include_scope=include_scope,
    )
    return OAuthSetupPlan(
        service=service,
        client_id=app.client_id,
        scopes=app.scopes,
        auth_url=auth_url,
        mode="configured_app",
        include_scope_in_url=include_scope,
        app_id=app.app_id,
        app_name=app.app_name,
    )


def plan_oauth_app_setup(config: dict[str, Any], *, app_id: str) -> OAuthSetupPlan:
    app = configured_oauth_app_by_id(config, app_id)
    if app is None:
        raise ValueError(f"No configured OAuth app: {app_id}")
    if not app.scopes:
        raise ValueError(
            f"Configured OAuth app '{app_id}' has no scopes. "
            "Set oauth_apps.catalog.<app_id>.scopes."
        )

    include_scope = not app.omit_scope_in_url
    auth_url = build_approval_url(
        config,
        client_id=app.client_id,
        scopes=app.scopes,
        include_scope=include_scope,
    )
    return OAuthSetupPlan(
        service=",".join(app.services or (app.service,)),
        client_id=app.client_id,
        scopes=app.scopes,
        auth_url=auth_url,
        mode="configured_app",
        include_scope_in_url=include_scope,
        app_id=app.app_id,
        app_name=app.app_name,
    )
