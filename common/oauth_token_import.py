"""Shared managed OAuth token import flow."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.auth import (
    VerifiedTokenIdentity,
    load_token_file,
    save_token_file,
    verify_token_identity,
)
from common.config import (
    choose_account_alias,
    find_token_account_by_email,
    yandex_identity_matches,
)
from common.oauth_apps import (
    OAuthClientMetadataCaptchaError,
    UNRESOLVED_SCOPE,
    fetch_yandex_oauth_client_metadata,
    oauth_app_for_client_id,
    upsert_agent_oauth_app,
)


@dataclass(frozen=True)
class ManagedTokenImportResult:
    """Result of importing one verified OAuth token into managed auth."""

    identity: VerifiedTokenIdentity
    resolved_account: str
    token_path: Path
    token_data: dict[str, Any]
    warnings: list[str]

    @property
    def token_count(self) -> int:
        """Return the number of stored token bindings in the account file."""
        return len([key for key in self.token_data if key != "email"])


def _write_agent_oauth_app(
    *,
    agent_config: dict[str, Any],
    agent_config_path: str | Path,
    client_id: str,
    scopes: list[str],
    app_name: str | None,
) -> str:
    """Persist one agent-local OAuth app definition and return its app id."""
    updated_agent_config = dict(agent_config)
    updated_agent_config.pop("accounts", None)
    app_id = upsert_agent_oauth_app(
        updated_agent_config,
        client_id=client_id,
        scopes=scopes,
        app_name=app_name,
    )
    path = Path(agent_config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(updated_agent_config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return app_id


def import_managed_oauth_token(
    *,
    config: dict[str, Any],
    data_dir: str | Path,
    agent_config: dict[str, Any],
    agent_config_path: str | Path,
    token: str,
    email: str | None = None,
    account: str | None = None,
    service: str | None = None,
    selected_app_id: str | None = None,
) -> ManagedTokenImportResult:
    """Verify and store a managed OAuth token under the requested or resolved account file."""
    identity = verify_token_identity(config, token=token)

    warnings: list[str] = []
    if email and not yandex_identity_matches(email, identity.email):
        warnings.append(
            f'Provided --email "{email}" differs from verified token identity '
            f'"{identity.email}". Storing verified identity email in the token file.'
        )

    existing_account = find_token_account_by_email(data_dir, identity.email)
    if existing_account is not None:
        resolved_account = existing_account["alias"]
        if account and account != resolved_account:
            warnings.append(
                f'Provided --account "{account}" does not match existing account '
                f'"{resolved_account}" for {identity.email}. Using "{resolved_account}".'
            )
    elif account:
        resolved_account = account
    else:
        resolved_account = choose_account_alias(data_dir, identity.email)

    matched_app = oauth_app_for_client_id(config, identity.client_id, service=service)
    if selected_app_id and matched_app is not None and matched_app.app_id != selected_app_id:
        warnings.append(
            f'Token client_id {identity.client_id} maps to configured app "{matched_app.app_id}", '
            f'not the selected app "{selected_app_id}". Saving as a non-standard token.'
        )
    elif selected_app_id and matched_app is None:
        warnings.append(
            f'Token client_id {identity.client_id} does not match the selected app "{selected_app_id}". '
            "Saving as a non-standard token."
        )

    if matched_app is None:
        warnings.append(
            f"Token client_id {identity.client_id} is not in the shipped OAuth app catalog. "
            "Resolving live OAuth client metadata before saving a custom-app token."
        )
        client_metadata = None
        try:
            client_metadata = fetch_yandex_oauth_client_metadata(
                config,
                client_id=identity.client_id,
            )
        except OAuthClientMetadataCaptchaError as exc:
            app_id = _write_agent_oauth_app(
                agent_config=agent_config,
                agent_config_path=agent_config_path,
                client_id=identity.client_id,
                scopes=[UNRESOLVED_SCOPE],
                app_name=f"Unresolved Yandex OAuth app {identity.client_id[:8]}",
            )
            detail = f" ({exc.captcha_page})" if exc.captcha_page else ""
            warnings.append(
                f"Live Yandex OAuth client metadata returned CAPTCHA JSON{detail}. "
                f'Created agent-local OAuth app "{app_id}" with scopes ["{UNRESOLVED_SCOPE}"]. '
                "Managed auth must resolve it from Yandex before actual use."
            )
        except (RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"Cannot import unknown OAuth client_id {identity.client_id}: "
                f"live OAuth client metadata lookup failed ({exc}). "
                "Add the client_id to oauth_apps.catalog with verified scopes, "
                "or retry after Yandex metadata is available."
            ) from exc

        if client_metadata is not None:
            app_id = _write_agent_oauth_app(
                agent_config=agent_config,
                agent_config_path=agent_config_path,
                client_id=client_metadata.client_id,
                scopes=client_metadata.scopes,
                app_name=client_metadata.app_name,
            )
            warnings.append(
                f'Created agent-local OAuth app "{app_id}" for client_id {identity.client_id}.'
            )

    token_path = Path(data_dir) / "auth" / f"{resolved_account}.token"
    try:
        token_data = load_token_file(token_path)
    except FileNotFoundError:
        token_data = {"email": identity.email}
    token_data["email"] = identity.email
    token_data.pop("token_meta", None)
    for key in list(token_data):
        if str(key).startswith("token."):
            token_data.pop(key, None)
    token_data[token] = {"client_id": identity.client_id}
    save_token_file(token_path, token_data)

    return ManagedTokenImportResult(
        identity=identity,
        resolved_account=resolved_account,
        token_path=token_path,
        token_data=token_data,
        warnings=warnings,
    )
