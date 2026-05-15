"""Shared managed OAuth token import flow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

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
from common.oauth_apps import oauth_app_for_client_id, upsert_agent_oauth_app


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
    selected_scopes: list[str] | None = None,
    permissions_note_provider: Callable[[], str | None] | None = None,
    account_context_only: bool = False,
) -> ManagedTokenImportResult:
    """Verify and store a managed OAuth token under the resolved account file."""
    identity = verify_token_identity(config, token=token)

    warnings: list[str] = []
    if email and not yandex_identity_matches(email, identity.email):
        warnings.append(
            f'Provided --email "{email}" differs from verified token identity '
            f'"{identity.email}". Writing the token by verified identity.'
        )

    if account_context_only and account:
        resolved_account = account
    else:
        existing_account = find_token_account_by_email(data_dir, identity.email)
        if existing_account is not None:
            resolved_account = existing_account["alias"]
            if account and account != resolved_account:
                warnings.append(
                    f'Provided --account "{account}" does not match existing account '
                    f'"{resolved_account}" for {identity.email}. Using "{resolved_account}".'
                )
        else:
            resolved_account = choose_account_alias(data_dir, identity.email)
            if account and account != resolved_account:
                warnings.append(
                    f'Provided --account "{account}" differs from token-resolved account '
                    f'"{resolved_account}". Writing "{resolved_account}".'
                )

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
            "Saving as a custom-app token."
        )
        permissions_note = (
            permissions_note_provider() if permissions_note_provider is not None else None
        )
        updated_agent_config = dict(agent_config)
        updated_agent_config.pop("accounts", None)
        app_id = upsert_agent_oauth_app(
            updated_agent_config,
            client_id=identity.client_id,
            scopes=selected_scopes or [],
            app_name=permissions_note,
        )
        path = Path(agent_config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(updated_agent_config, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
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
