"""Shared token resolution for all Yandex sub-skills."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
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
class TokenRef:
    token: str
    client_id: str
    source_key: str
    good_at: str | None = None
    bad_at: str | None = None


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


def _token_object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def token_refs(token_data: dict[str, Any]) -> list[TokenRef]:
    refs: list[TokenRef] = []
    for key, value in token_data.items():
        if key == "email" or key.startswith("token."):
            continue
        token_value = str(key).strip()
        entry = _token_object(value)
        client_id = str(entry.get("client_id", "")).strip()
        if not token_value or not client_id:
            continue
        good_at = str(entry.get("good_at") or "").strip() or None
        bad_at = str(entry.get("bad_at") or "").strip() or None
        if good_at and bad_at:
            raise TokenResolutionError(
                "Token state cannot contain both good_at and bad_at",
                token_key=token_value,
            )
        refs.append(
            TokenRef(
                token=token_value,
                client_id=client_id,
                source_key=token_value,
                good_at=good_at,
                bad_at=bad_at,
            )
        )
    return refs


TokenIdentityVerifier = Callable[[dict[str, Any], str], VerifiedTokenIdentity]


def _default_token_identity_verifier(config: dict[str, Any], token: str) -> VerifiedTokenIdentity:
    """Verify a legacy token value through Yandex before converting storage."""

    return verify_token_identity(config, token=token)


def _normalize_legacy_tokens(
    token_data: dict[str, Any],
    config: dict[str, Any],
    *,
    verify_identity: TokenIdentityVerifier,
) -> bool:
    """Convert recoverable legacy `token.<service>` entries in memory.

    The new token file model stores OAuth token values as top-level keys.  A
    legacy service key does not carry a trustworthy `client_id`, so conversion
    verifies the token value and uses Yandex's returned `email` + `client_id`
    binding as the source of truth.
    """

    changed = False
    for legacy_key in _legacy_token_keys(token_data):
        token_value = str(token_data.get(legacy_key) or "").strip()
        if not token_value:
            continue
        identity = verify_identity(config, token_value)
        if identity.email:
            token_data["email"] = identity.email
        token_data[token_value] = {"client_id": identity.client_id}
        token_data.pop(legacy_key, None)
        changed = True
    return changed


def load_prepared_token_file(
    token_path: str | Path,
    config: dict[str, Any],
    *,
    verify_identity: TokenIdentityVerifier | None = None,
) -> dict[str, Any]:
    """Load token state, delete forbidden metadata, and convert legacy tokens.

    This is the shared stateless load phase for GH41: token files are normalized
    before a caller selects candidates, and every mutation is persisted
    immediately so failed legacy conversion cannot leave ``token_meta`` behind.
    """

    token_data = load_token_file(token_path)
    if "token_meta" in token_data:
        token_data.pop("token_meta", None)
        save_token_file(token_path, token_data)
    if _normalize_legacy_tokens(
        token_data,
        config,
        verify_identity=verify_identity or _default_token_identity_verifier,
    ):
        save_token_file(token_path, token_data)
    _reject_legacy_token_keys(token_data)
    return token_data


def _legacy_token_keys(token_data: dict[str, Any]) -> list[str]:
    return sorted(key for key in token_data if key.startswith("token."))


def _raise_legacy_token_error(token_key: str) -> None:
    raise TokenResolutionError(
        f"Legacy token entry {token_key} must be converted through token verification",
        token_key=token_key,
    )


def _reject_legacy_token_keys(token_data: dict[str, Any]) -> None:
    """Fail deterministically when a legacy key could not be converted."""

    legacy_keys = _legacy_token_keys(token_data)
    if legacy_keys:
        _raise_legacy_token_error(legacy_keys[0])


def get_token_entry(token_data: dict[str, Any], token_key: str) -> dict[str, Any]:
    """Return the token object stored under the OAuth token value."""

    return _token_object(token_data.get(token_key))


def set_token_client_id(
    token_data: dict[str, Any],
    token_key: str,
    *,
    client_id: str | None = None,
) -> None:
    """Set the config-backed app binding on a token object."""

    current = _token_object(token_data.get(token_key))
    if client_id:
        current["client_id"] = client_id
    if current:
        token_data[token_key] = current


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
    token_entry = get_token_entry(token_data, token_key)
    scopes = token_entry.get("scopes")
    if isinstance(scopes, list):
        return {str(item) for item in scopes if str(item).strip()}
    return set()


def _catalog_app_for_client_id(config: dict[str, Any], client_id: str) -> dict[str, Any] | None:
    catalog = config.get("oauth_apps", {}).get("catalog", {})
    if not isinstance(catalog, dict):
        return None
    normalized_client_id = str(client_id).strip()
    for raw in catalog.values():
        if not isinstance(raw, dict):
            continue
        if str(raw.get("client_id", "")).strip() == normalized_client_id:
            return raw
    return None


def _catalog_scopes(config: dict[str, Any], client_id: str) -> set[str]:
    raw = _catalog_app_for_client_id(config, client_id)
    scopes = raw.get("scopes") if raw is not None else None
    if isinstance(scopes, list):
        return {str(scope).strip() for scope in scopes if str(scope).strip()}
    return set()


def _token_satisfies_scopes(
    token_data: dict[str, Any],
    token_key: str,
    required_scopes: list[str] | None,
    *,
    config: dict[str, Any] | None = None,
) -> bool:
    if not required_scopes:
        return True
    granted = _token_scopes(token_data, token_key)
    if config is not None:
        client_id = str(get_token_entry(token_data, token_key).get("client_id") or "").strip()
        granted.update(_catalog_scopes(config, client_id))
    if not granted:
        return False
    return set(required_scopes).issubset(granted)


def _approval_details(
    token_data: dict[str, Any],
    config: dict[str, Any],
    *,
    token_key: str,
    required_scopes: list[str],
) -> dict[str, Any]:
    token_entry = get_token_entry(token_data, token_key)
    client_id = token_entry.get("client_id")
    if not client_id:
        return {}
    combined_scopes = set(required_scopes)
    combined_scopes.update(_token_scopes(token_data, token_key))
    combined_scopes.update(_catalog_scopes(config, str(client_id)))
    approval_url = build_approval_url(
        config,
        client_id=client_id,
        scopes=sorted(combined_scopes),
    )
    return {
        "approval_url": approval_url,
        "missing_scopes": sorted(
            set(required_scopes)
            - _token_scopes(token_data, token_key)
            - _catalog_scopes(config, str(client_id))
        ),
    }


def resolve_token(
    *,
    account: str,
    skill: str,
    data_dir: str | Path,
    config: dict[str, Any],
    required_scopes: list[str] | None = None,
    verify_identity: TokenIdentityVerifier | None = None,
) -> ResolvedToken:
    if skill == "search":
        raise ValueError("search does not use token-file auth")

    data_path = Path(data_dir).resolve()
    token_path = data_path / "auth" / f"{account}.token"
    token_data = load_prepared_token_file(
        token_path,
        config,
        verify_identity=verify_identity,
    )
    canonical_key = canonical_token_key(skill)

    token_value = token_data.get(canonical_key)
    if token_value and _token_satisfies_scopes(
        token_data,
        canonical_key,
        required_scopes,
        config=config,
    ):
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

    for token_ref in token_refs(token_data):
        token_key = token_ref.source_key
        if _token_satisfies_scopes(
            token_data,
            token_key,
            required_scopes,
            config=config,
        ):
            return ResolvedToken(
                account=account,
                skill=skill,
                token=token_ref.token,
                token_key=token_key,
                source_key=token_key,
                token_path=token_path,
                token_data=token_data,
                email=token_data.get("email"),
            )

    refs = token_refs(token_data)
    if refs:
        details = _approval_details(
            token_data,
            config,
            token_key=refs[0].source_key,
            required_scopes=required_scopes or [],
        )
        raise TokenResolutionError(
            f"No token with required scopes resolved for {skill} account {account}",
            account=account,
            skill=skill,
            token_key=refs[0].source_key,
            **details,
        )

    raise TokenResolutionError(
        f"No token resolved for {skill} account {account}",
        account=account,
        skill=skill,
        token_key=canonical_key,
        token_path=str(token_path),
    )
