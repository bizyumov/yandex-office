"""Shared token resolution for all Yandex sub-skills."""

from __future__ import annotations

import copy
from contextlib import contextmanager
import errno
import json
import os
from dataclasses import dataclass
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from common.config import resolve_auth_file, resolve_data_dir


class TokenResolutionError(RuntimeError):
    """Structured token resolution failure."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        payload = {"error": str(self)}
        payload.update(self.details)
        return payload


class TokenFileUpdateError(RuntimeError):
    """Token persistence failed without exposing account or filesystem details."""


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


@contextmanager
def _token_file_lock(token_path: str | Path) -> Iterator[None]:
    """Serialize cross-process access to one token file."""

    path = Path(token_path)
    lock_path = path.with_name(path.name + ".lock")
    fd = -1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        _lock_file_descriptor(fd)
    except OSError:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        raise TokenFileUpdateError("Token file lock failed") from None
    try:
        yield
    finally:
        try:
            _unlock_file_descriptor(fd)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass


def _lock_file_descriptor(fd: int) -> None:
    """Acquire one blocking byte-range lock on Windows or flock on POSIX."""

    if os.name != "nt":
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)
        return

    import msvcrt

    if os.fstat(fd).st_size == 0:
        os.write(fd, b"\0")
        os.fsync(fd)
    while True:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EDEADLK}:
                raise
            time.sleep(0.05)


def _unlock_file_descriptor(fd: int) -> None:
    """Release the platform-specific token transaction lock."""

    if os.name != "nt":
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)
        return

    import msvcrt

    os.lseek(fd, 0, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def _fsync_directory(directory: Path) -> None:
    """Persist a completed atomic replacement on POSIX filesystems."""

    if os.name == "nt":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _save_token_file_unlocked(token_path: str | Path, payload: dict[str, Any]) -> None:
    """Atomically replace one token file while its transaction lock is held."""

    path = Path(token_path)
    fd = -1
    temp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temp_path = Path(temp_name)
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        handle = os.fdopen(fd, "w", encoding="utf-8")
        fd = -1
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    except OSError:
        raise TokenFileUpdateError("Token file update failed") from None
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def save_token_file(token_path: str | Path, payload: dict[str, Any]) -> None:
    """Atomically overwrite one token file under its cross-process lock."""

    with _token_file_lock(token_path):
        _save_token_file_unlocked(token_path, payload)


TokenFileCheckpoint = Callable[[], None]
TokenFileUpdater = Callable[[dict[str, Any], TokenFileCheckpoint], dict[str, Any] | None]
TokenFileLoader = Callable[[str | Path], dict[str, Any]]
TokenFileSaver = Callable[[str | Path, dict[str, Any]], None]


def update_token_file(
    token_path: str | Path,
    update: TokenFileUpdater,
    *,
    create: bool = False,
    _load: TokenFileLoader | None = None,
    _save: TokenFileSaver | None = None,
) -> dict[str, Any]:
    """Apply one read-modify-write token transaction under an exclusive lock."""

    path = Path(token_path)
    loader = _load or load_token_file
    with _token_file_lock(path):
        try:
            token_data = loader(path)
        except FileNotFoundError:
            if not create:
                raise
            token_data = {}
        except OSError:
            raise TokenFileUpdateError("Token file read failed") from None
        before = copy.deepcopy(token_data)

        def persist(payload: dict[str, Any]) -> None:
            try:
                if _save is None or _save is save_token_file:
                    _save_token_file_unlocked(path, payload)
                else:
                    _save(path, payload)
            except OSError:
                raise TokenFileUpdateError("Token file update failed") from None

        def checkpoint() -> None:
            nonlocal before
            if token_data != before or not path.exists():
                persist(token_data)
                before = copy.deepcopy(token_data)

        updated = update(token_data, checkpoint)
        if updated is None:
            updated = token_data
        if not isinstance(updated, dict):
            raise TypeError("Token update must return a dictionary or None")
        if updated != before or not path.exists():
            persist(updated)
        return updated


def _token_object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def token_refs(token_data: dict[str, Any]) -> list[TokenRef]:
    refs: list[TokenRef] = []
    for key, value in token_data.items():
        if key == "email" or key.startswith("token."):
            continue
        entry = _token_object(value)
        token_value = str(entry.get("access_token", key)).strip()
        client_id = str(entry.get("client_id", "")).strip()
        if not token_value or not client_id:
            continue
        good_at = str(entry.get("good_at") or "").strip() or None
        bad_at = str(entry.get("bad_at") or "").strip() or None
        if good_at and bad_at:
            raise TokenResolutionError(
                "Token state cannot contain both good_at and bad_at",
                token_key=key,
            )
        refs.append(
            TokenRef(
                token=token_value,
                client_id=client_id,
                source_key=key,
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
    prepare_catalog: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Load token state, delete forbidden metadata, and convert legacy tokens.

    This is the shared stateless load phase for GH41: token files are normalized
    before a caller selects candidates, and every mutation is persisted
    immediately so failed legacy conversion cannot leave ``token_meta`` behind.
    """

    def prepare(token_data: dict[str, Any], checkpoint: TokenFileCheckpoint) -> dict[str, Any]:
        if "token_meta" in token_data:
            token_data.pop("token_meta", None)
            checkpoint()
        if _normalize_legacy_tokens(
            token_data,
            config,
            verify_identity=verify_identity or _default_token_identity_verifier,
        ):
            checkpoint()
        _reject_legacy_token_keys(token_data)
        if prepare_catalog is not None:
            prepare_catalog(token_data)
        converted = app_keyed_tokens(token_data, config)
        return converted

    return update_token_file(token_path, prepare)


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


def app_keyed_tokens(token_data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Convert bearer-keyed entries locally, preserving metadata and stable names.

    Unknown app mappings fail before callers write any data. Already named
    entries retain their keys. This function performs no I/O or network calls.
    """
    from common.oauth_apps import oauth_app_for_client_id

    result = dict(token_data)
    for key, value in token_data.items():
        if key == "email":
            continue
        if not isinstance(value, dict) or not value.get("client_id"):
            raise TokenResolutionError("Invalid token entry; migration not written")
        if "access_token" in value:
            if not isinstance(value["access_token"], str) or not value["access_token"].strip():
                raise TokenResolutionError("Empty access_token; migration not written")
            continue
        app = oauth_app_for_client_id(config, str(value["client_id"]))
        if app is None:
            raise TokenResolutionError("Unknown OAuth app; migration not written", client_id=value["client_id"])
        number = 1
        while f"{app.app_id}-{number}" in result:
            number += 1
        result[f"{app.app_id}-{number}"] = {**value, "access_token": key}
        del result[key]
    return result


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
        return {
            str(scope).strip()
            for scope in scopes
            if str(scope).strip() and str(scope).strip() != "unresolved"
        }
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

    resolve_data_dir(data_dir_override=data_dir)
    token_path = resolve_auth_file(f"{account}.token")
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
