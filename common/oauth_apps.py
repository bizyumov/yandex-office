"""Shared planning logic for Yandex OAuth token setup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from common.auth import build_approval_url, default_scopes


SERVICE_SCOPES = {
    "auth": [],
    "calendar": default_scopes("calendar", "read"),
    "contacts": default_scopes("contacts", "read"),
    "directory": default_scopes("directory", "read"),
    "disk": default_scopes("disk", "read"),
    "forms": default_scopes("forms", "read"),
    "mail": default_scopes("mail", "read"),
    "telemost": default_scopes("telemost", "write"),
    "tracker": default_scopes("tracker", "read"),
}


@dataclass(frozen=True)
class OAuthAppConfig:
    service: str
    client_id: str
    scopes: list[str]
    app_id: str
    app_name: str | None = None
    omit_scope_in_url: bool = True


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


def configured_oauth_app(
    config: dict[str, Any],
    service: str,
    app_id: str | None = None,
) -> OAuthAppConfig | None:
    apps = config.get("oauth_apps")
    if not isinstance(apps, dict):
        return None

    catalog = apps.get("catalog")
    service_defaults = apps.get("service_defaults")
    if not isinstance(catalog, dict) or not isinstance(service_defaults, dict):
        return None

    resolved_app_id = str(app_id or service_defaults.get(service, "")).strip()
    if not resolved_app_id:
        return None

    raw = catalog.get(resolved_app_id)
    if not isinstance(raw, dict):
        return None

    configured_service = str(raw.get("service", "")).strip()
    if configured_service != service:
        raise ValueError(
            f"OAuth app '{resolved_app_id}' is configured for service "
            f"'{configured_service or '(missing)'}', not '{service}'"
        )

    client_id = str(raw.get("client_id", "")).strip()
    if not client_id:
        return None

    app_name = str(raw.get("app_name", "")).strip() or None
    scopes = _clean_scopes(raw.get("scopes"))
    if not scopes:
        scopes = list(SERVICE_SCOPES.get(service, []))

    omit_scope_in_url = raw.get("omit_scope_in_url", True)
    return OAuthAppConfig(
        service=service,
        client_id=client_id,
        scopes=scopes,
        app_id=resolved_app_id,
        app_name=app_name,
        omit_scope_in_url=bool(omit_scope_in_url),
    )


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
    apps = config.get("oauth_apps")
    if not isinstance(apps, dict):
        return []

    catalog = apps.get("catalog")
    service_defaults = apps.get("service_defaults")
    if not isinstance(catalog, dict) or not isinstance(service_defaults, dict):
        return []

    default_app_id = str(service_defaults.get(service, "")).strip() or None
    options: list[OAuthProfileOption] = []
    for app_id in sorted(catalog):
        raw = catalog.get(app_id)
        if not isinstance(raw, dict):
            continue
        configured_service = str(raw.get("service", "")).strip()
        if configured_service != service:
            continue
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


def plan_oauth_setup(
    config: dict[str, Any],
    *,
    service: str,
    app_id: str | None = None,
    client_id: str | None = None,
    extra_scopes: list[str] | None = None,
) -> OAuthSetupPlan:
    if service not in SERVICE_SCOPES:
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
        scopes = explicit_scopes or list(SERVICE_SCOPES[service])
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
            "Add oauth_apps.service_defaults.<service> plus oauth_apps.catalog.<app_id> in config.json, "
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
