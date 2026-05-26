"""Shared planning logic for Yandex OAuth token setup."""

from __future__ import annotations

import json
from dataclasses import dataclass
import os
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    client_id: str
    scopes: list[str]
    auth_url: str
    mode: str
    include_scope_in_url: bool
    app_id: str | None = None
    app_name: str | None = None


@dataclass(frozen=True)
class OAuthClientMetadata:
    client_id: str
    app_name: str | None
    scopes: list[str]


UNRESOLVED_SCOPE = "unresolved"
YANDEX_OAUTH_CLIENT_INFO_URL = "https://oauth.yandex.com/client/{client_id}/info?format=json"


class OAuthClientMetadataCaptchaError(RuntimeError):
    """Yandex returned CAPTCHA JSON instead of OAuth client metadata."""

    def __init__(self, message: str, *, captcha_page: str | None = None) -> None:
        super().__init__(message)
        self.captcha_page = captcha_page


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Unknown/non-public client ids redirect to Passport. Treat that as an
        # unresolved metadata lookup instead of parsing the login HTML.
        return None


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


def configured_oauth_app(
    config: dict[str, Any],
    service: str,
    app_id: str,
) -> OAuthAppConfig | None:
    catalog = _oauth_catalog(config)
    resolved_app_id = str(app_id).strip()
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
        if str(raw.get("client_id", "")).strip() != normalized_client_id:
            continue
        if service is not None and configured_services and service not in configured_services:
            continue
        if not configured_services:
            return OAuthAppConfig(
                service=service or "",
                client_id=normalized_client_id,
                scopes=_clean_scopes(raw.get("scopes")),
                app_id=str(app_id),
                app_name=str(raw.get("app_name") or raw.get("name") or "").strip() or None,
                omit_scope_in_url=bool(raw.get("omit_scope_in_url", True)),
                services=(),
            )
        return configured_oauth_app(config, service or configured_services[0], app_id)
    return None


def fetch_yandex_oauth_client_metadata(
    config: dict[str, Any],
    *,
    client_id: str,
    timeout: float = 10.0,
) -> OAuthClientMetadata:
    normalized_client_id = str(client_id).strip()
    if not normalized_client_id:
        raise ValueError("client_id must be non-empty")

    # Yandex online is the only source of truth for OAuth client scopes.
    # The config argument is retained for API compatibility; this endpoint is
    # intentionally not configurable.
    info_template = YANDEX_OAUTH_CLIENT_INFO_URL
    info_url = info_template.format(client_id=quote(normalized_client_id, safe=""))
    request = Request(info_url)
    opener = build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(
            f"Yandex OAuth client metadata lookup failed with HTTP {exc.code}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"Yandex OAuth client metadata lookup failed: {exc.reason}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Yandex OAuth client metadata returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("Yandex OAuth client metadata returned non-object JSON")

    if str(payload.get("type") or "").strip().lower() == "captcha":
        captcha = payload.get("captcha")
        captcha_page = (
            str(captcha.get("captcha-page") or "").strip()
            if isinstance(captcha, dict)
            else ""
        )
        detail = f": {captcha_page}" if captcha_page else ""
        raise OAuthClientMetadataCaptchaError(
            f"Yandex OAuth client metadata lookup returned captcha JSON{detail}",
            captcha_page=captcha_page or None,
        )

    response_client_id = str(payload.get("id") or "").strip()
    if response_client_id and response_client_id != normalized_client_id:
        raise RuntimeError(
            "Yandex OAuth client metadata returned a different client_id"
        )

    scopes = _clean_scopes(payload.get("scope"))
    if not scopes:
        raise RuntimeError("Yandex OAuth client metadata did not include scopes")

    app_name = str(payload.get("name") or "").strip() or None
    return OAuthClientMetadata(
        client_id=normalized_client_id,
        app_name=app_name,
        scopes=scopes,
    )


def _local_app_id(client_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", client_id.lower()).strip("-")
    return f"custom-{normalized[:24] or 'app'}"


def upsert_agent_oauth_app(
    agent_config: dict[str, Any],
    *,
    client_id: str,
    scopes: list[str],
    app_name: str | None = None,
) -> str:
    normalized_client_id = str(client_id).strip()
    if not normalized_client_id:
        raise ValueError("client_id must be non-empty")

    apps = agent_config.setdefault("oauth_apps", {})
    if not isinstance(apps, dict):
        raise ValueError("oauth_apps must be an object")
    catalog = apps.setdefault("catalog", {})
    if not isinstance(catalog, dict):
        raise ValueError("oauth_apps.catalog must be an object")

    for app_id, raw in sorted(catalog.items()):
        if isinstance(raw, dict) and str(raw.get("client_id", "")).strip() == normalized_client_id:
            raw["scopes"] = _clean_scopes(scopes)
            if app_name:
                raw["name"] = app_name
            return str(app_id)

    base_id = _local_app_id(normalized_client_id)
    app_id = base_id
    suffix = 2
    while app_id in catalog:
        app_id = f"{base_id}-{suffix}"
        suffix += 1
    catalog[app_id] = {
        "client_id": normalized_client_id,
        "scopes": _clean_scopes(scopes),
        "name": app_name or f"Custom Yandex OAuth app {normalized_client_id[:8]}",
        "omit_scope_in_url": False,
    }
    return app_id


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
        client_id=app.client_id,
        scopes=app.scopes,
        auth_url=auth_url,
        mode="configured_app",
        include_scope_in_url=include_scope,
        app_id=app.app_id,
        app_name=app.app_name,
    )
