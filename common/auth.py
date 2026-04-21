"""Shared token resolution for all Yandex sub-skills."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class TokenResolutionError(RuntimeError):
    """Structured token resolution failure."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        payload = {"error": str(self)}
        payload.update(self.details)
        return payload


@dataclass(frozen=True)
class ResolvedToken:
    account: str
    skill: str
    token: str
    token_key: str
    source_key: str
    token_path: Path
    token_data: dict[str, Any]
    email: str | None = None


@dataclass(frozen=True)
class VerifiedTokenIdentity:
    email: str
    client_id: str
    subject_id: str | None = None
    raw: dict[str, Any] | None = None


def canonical_token_key(skill: str) -> str:
    normalized = str(skill).strip().lower()
    if not normalized:
        raise ValueError("Skill name must be non-empty")
    return f"token.{normalized}"


def load_token_file(token_path: str | Path) -> dict[str, Any]:
    path = Path(token_path)
    if not path.exists():
        raise FileNotFoundError(f"Token file not found: {path}")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def save_token_file(token_path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(token_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temp_path.replace(path)
    path.chmod(0o600)


def _token_meta_store(token_data: dict[str, Any]) -> dict[str, Any]:
    value = token_data.get("token_meta")
    if isinstance(value, dict):
        return value
    return {}


def get_token_metadata(token_data: dict[str, Any], token_key: str) -> dict[str, Any]:
    meta = _token_meta_store(token_data)
    data = meta.get(token_key)
    return dict(data) if isinstance(data, dict) else {}


def set_token_metadata(
    token_data: dict[str, Any],
    token_key: str,
    *,
    scopes: list[str] | None = None,
    client_id: str | None = None,
    app_id: str | None = None,
    verified_email: str | None = None,
    permissions_note: str | None = None,
) -> None:
    meta = dict(_token_meta_store(token_data))
    current = dict(meta.get(token_key) or {})
    if scopes:
        current["scopes"] = sorted(set(scopes))
    if client_id:
        current["client_id"] = client_id
    if app_id:
        current["app_id"] = app_id
    if verified_email:
        current["verified_email"] = verified_email
    if permissions_note:
        current["permissions_note"] = permissions_note
    meta[token_key] = current
    token_data["token_meta"] = meta


def build_approval_url(
    config: dict[str, Any],
    *,
    client_id: str,
    scopes: list[str],
    include_scope: bool = True,
) -> str:
    oauth_base = config.get("urls", {}).get(
        "oauth",
        "https://oauth.yandex.ru/authorize",
    )
    params_dict = {
        "response_type": "token",
        "client_id": client_id,
    }
    if include_scope and scopes:
        params_dict["scope"] = " ".join(sorted(set(scopes)))
    params = urlencode(params_dict)
    return f"{oauth_base}?{params}"


def verify_token_identity(
    config: dict[str, Any],
    *,
    token: str,
    timeout: float = 10.0,
) -> VerifiedTokenIdentity:
    raw_token = str(token).strip()
    if not raw_token:
        raise RuntimeError("Token cannot be empty")

    info_base = config.get("urls", {}).get("oauth_info", "https://login.yandex.ru/info")
    separator = "&" if "?" in info_base else "?"
    info_url = f"{info_base}{separator}{urlencode({'format': 'json'})}"
    request = Request(
        info_url,
        headers={
            "Authorization": f"OAuth {raw_token}",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Yandex token validation failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"Yandex token validation request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Yandex token validation returned invalid JSON") from exc

    email = str(payload.get("login") or payload.get("default_email") or "").strip()
    client_id = str(payload.get("client_id") or "").strip()
    if not email:
        raise RuntimeError("Yandex token validation response did not include login/email")
    if not client_id:
        raise RuntimeError("Yandex token validation response did not include client_id")

    subject_id = str(payload.get("id") or "").strip() or None
    return VerifiedTokenIdentity(
        email=email,
        client_id=client_id,
        subject_id=subject_id,
        raw=payload,
    )


def _token_scopes(token_data: dict[str, Any], token_key: str) -> set[str]:
    meta = get_token_metadata(token_data, token_key)
    scopes = meta.get("scopes")
    if isinstance(scopes, list):
        return {str(item) for item in scopes if str(item).strip()}
    return set()


def _token_satisfies_scopes(
    token_data: dict[str, Any],
    token_key: str,
    required_scopes: list[str] | None,
) -> bool:
    if not required_scopes:
        return True
    granted = _token_scopes(token_data, token_key)
    if not granted:
        return True
    return set(required_scopes).issubset(granted)


def _approval_details(
    token_data: dict[str, Any],
    config: dict[str, Any],
    *,
    token_key: str,
    required_scopes: list[str],
) -> dict[str, Any]:
    token_meta = get_token_metadata(token_data, token_key)
    client_id = token_meta.get("client_id")
    if not client_id:
        return {}
    combined_scopes = set(required_scopes)
    combined_scopes.update(_token_scopes(token_data, token_key))
    approval_url = build_approval_url(
        config,
        client_id=client_id,
        scopes=sorted(combined_scopes),
    )
    return {
        "approval_url": approval_url,
        "missing_scopes": sorted(set(required_scopes) - _token_scopes(token_data, token_key)),
    }


def resolve_token(
    *,
    account: str,
    skill: str,
    data_dir: str | Path,
    config: dict[str, Any],
    required_scopes: list[str] | None = None,
) -> ResolvedToken:
    if skill == "search":
        raise ValueError("search does not use token-file auth")

    data_path = Path(data_dir).resolve()
    token_path = data_path / "auth" / f"{account}.token"
    token_data = load_token_file(token_path)
    canonical_key = canonical_token_key(skill)

    token_value = token_data.get(canonical_key)
    if token_value and _token_satisfies_scopes(token_data, canonical_key, required_scopes):
        return ResolvedToken(
            account=account,
            skill=skill,
            token=str(token_value),
            token_key=canonical_key,
            source_key=canonical_key,
            token_path=token_path,
            token_data=token_data,
            email=token_data.get("email"),
        )

    if token_value:
        details = _approval_details(
            token_data,
            config,
            token_key=canonical_key,
            required_scopes=required_scopes or [],
        )
        raise TokenResolutionError(
            f"{canonical_key} lacks required scopes for {skill}",
            account=account,
            skill=skill,
            token_key=canonical_key,
            **details,
        )

    raise TokenResolutionError(
        f"No token resolved for {skill} account {account}",
        account=account,
        skill=skill,
        token_key=canonical_key,
        token_path=str(token_path),
    )
