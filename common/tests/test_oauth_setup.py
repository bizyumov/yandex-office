from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.oauth_setup import configured_oauth_app, plan_oauth_setup


def test_configured_oauth_app_uses_service_defaults_when_scopes_omitted() -> None:
    app = configured_oauth_app(
        {
            "oauth_apps": {
                "service_defaults": {"mail": "mail-readonly"},
                "catalog": {
                    "mail-readonly": {
                        "service": "mail",
                        "app_name": "OpenClaw Yandex Mail Readonly",
                        "client_id": "mail-client-id",
                    }
                }
            }
        },
        "mail",
    )

    assert app is not None
    assert app.app_id == "mail-readonly"
    assert app.app_name == "OpenClaw Yandex Mail Readonly"
    assert app.client_id == "mail-client-id"
    assert app.scopes == ["mail:imap_ro"]
    assert app.omit_scope_in_url is True


def test_plan_oauth_setup_prefers_configured_app_without_scope_parameter() -> None:
    plan = plan_oauth_setup(
        {
            "urls": {"oauth": "https://oauth.yandex.ru/authorize"},
            "oauth_apps": {
                "service_defaults": {"telemost": "telemost-default"},
                "catalog": {
                    "telemost-default": {
                        "service": "telemost",
                        "app_name": "OpenClaw Yandex Telemost Default",
                        "client_id": "telemost-client-id",
                        "scopes": [
                            "telemost-api:conferences.create",
                            "telemost-api:conferences.delete",
                            "telemost-api:conferences.read",
                            "telemost-api:conferences.update",
                        ],
                    }
                }
            },
        },
        service="telemost",
    )

    assert plan.mode == "configured_app"
    assert plan.app_id == "telemost-default"
    assert plan.app_name == "OpenClaw Yandex Telemost Default"
    assert plan.client_id == "telemost-client-id"
    assert "scope=" not in plan.auth_url
    assert "client_id=telemost-client-id" in plan.auth_url


def test_plan_oauth_setup_explicit_mode_keeps_scope_parameter() -> None:
    plan = plan_oauth_setup(
        {"urls": {"oauth": "https://oauth.yandex.ru/authorize"}},
        service="disk",
        client_id="disk-client-id",
        extra_scopes=["cloud_api:disk.write", "cloud_api:disk.app_folder"],
    )

    assert plan.mode == "explicit"
    assert plan.client_id == "disk-client-id"
    assert "scope=" in plan.auth_url
    assert "client_id=disk-client-id" in plan.auth_url


def test_plan_oauth_setup_requires_explicit_scope_override_to_have_client_id() -> None:
    try:
        plan_oauth_setup(
            {"urls": {"oauth": "https://oauth.yandex.ru/authorize"}},
            service="mail",
            extra_scopes=["mail:imap_full"],
        )
    except ValueError as exc:
        assert "--scope overrides require --client-id" in str(exc)
    else:
        raise AssertionError("Expected ValueError for scope override without client id")


def test_plan_oauth_setup_can_select_service_compatible_non_default_app() -> None:
    plan = plan_oauth_setup(
        {
            "urls": {"oauth": "https://oauth.yandex.ru/authorize"},
            "oauth_apps": {
                "service_defaults": {"disk": "disk-read"},
                "catalog": {
                    "disk-read": {
                        "service": "disk",
                        "app_name": "OpenClaw Yandex Disk Read",
                        "client_id": "disk-read-client-id",
                        "scopes": ["cloud_api:disk.read"],
                    },
                    "disk-full": {
                        "service": "disk",
                        "app_name": "OpenClaw Yandex Disk Full",
                        "client_id": "disk-full-client-id",
                        "scopes": [
                            "cloud_api:disk.app_folder",
                            "cloud_api:disk.info",
                            "cloud_api:disk.read",
                            "cloud_api:disk.write",
                        ],
                    },
                },
            },
        },
        service="disk",
        app_id="disk-full",
    )

    assert plan.mode == "configured_app"
    assert plan.app_id == "disk-full"
    assert plan.client_id == "disk-full-client-id"
    assert plan.scopes == [
        "cloud_api:disk.app_folder",
        "cloud_api:disk.info",
        "cloud_api:disk.read",
        "cloud_api:disk.write",
    ]
    assert "scope=" not in plan.auth_url


def test_plan_oauth_setup_rejects_app_ids_for_another_service() -> None:
    try:
        plan_oauth_setup(
            {
                "urls": {"oauth": "https://oauth.yandex.ru/authorize"},
                "oauth_apps": {
                    "service_defaults": {"disk": "disk-read"},
                    "catalog": {
                        "tracker-read": {
                            "service": "tracker",
                            "client_id": "tracker-client-id",
                            "scopes": ["tracker:read"],
                        }
                    },
                },
            },
            service="disk",
            app_id="tracker-read",
        )
    except ValueError as exc:
        assert "is configured for service 'tracker', not 'disk'" in str(exc)
    else:
        raise AssertionError("Expected ValueError for cross-service app id")
