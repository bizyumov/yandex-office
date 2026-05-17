"""Decorator-driven Yandex API auth dispatch.

This module is the GH41 low-level runtime boundary:

- API methods declare their auth shape once with ``@yandex_api_method``.
- Runtime token selection uses token-file ``client_id`` values plus config app
  scopes.
- HTTP response handling centralizes the current matrix-backed auth split:
  only ``403 ForbiddenError`` rejects a token candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import functools
import os
from pathlib import Path
from typing import Any, Callable

import requests

from common.auth import (
    TokenRef,
    build_approval_url,
    load_token_file,
    load_prepared_token_file,
    save_token_file,
    token_refs,
    verify_token_identity,
)
from common.config import load_agent_config_payload, save_agent_config_payload
from common.oauth_apps import fetch_yandex_oauth_client_metadata, upsert_agent_oauth_app
from common.oauth_token_import import import_managed_oauth_token


LEGACY_DISK_TOKEN_ENV = "YANDEX_DISK_TOKEN"


class YandexApiError(RuntimeError):
    """Provider response that is not a token-rotation signal."""

    def __init__(
        self,
        *,
        provider_error: str | None,
        status_code: int,
        message: str,
        payload: Any = None,
    ) -> None:
        """Capture provider error details for callers and diagnostics."""
        super().__init__(message)
        self.provider_error = provider_error
        self.status_code = status_code
        self.payload = payload


class TokenRejected(YandexApiError):
    """The attempted token was rejected by the provider auth layer."""


class TokenConfigError(RuntimeError):
    """Token file and OAuth app catalog are inconsistent."""


class BlockedYandexMethodError(RuntimeError):
    """No eligible token could complete a decorated API method."""

    def __init__(
        self,
        message: str,
        *,
        method_id: str,
        required: dict[str, list[str] | bool],
        client_ids: list[str],
        authorization_urls: list[str],
    ) -> None:
        """Capture the missing method-auth context."""
        super().__init__(message)
        self.method_id = method_id
        self.required = required
        self.client_ids = client_ids
        self.authorization_urls = authorization_urls


@dataclass(frozen=True)
class MethodAuth:
    """Auth metadata declared by ``@yandex_api_method``."""

    method_id: str
    public: bool = False
    one_of: tuple[str, ...] = ()
    all_of: tuple[str, ...] = ()

    def requirement(self) -> dict[str, list[str] | bool]:
        """Return the serializable auth shape used by the audit command."""

        if self.public:
            return {"public": True}
        if self.one_of:
            return {"one_of": list(self.one_of)}
        return {"all_of": list(self.all_of)}


@dataclass(frozen=True)
class YandexApiContext:
    """State passed into decorated low-level API methods."""

    account: str | None
    data_dir: Path
    config: dict[str, Any]
    session: requests.Session
    token_ref: TokenRef | None = None
    token_data: dict[str, Any] | None = None

    def for_token(
        self,
        token_ref: TokenRef,
        *,
        token_path: Path,
        token_data: dict[str, Any],
    ) -> "YandexApiContext":
        """Return the same request context bound to one token candidate."""

        return YandexApiContext(
            account=self.account,
            data_dir=self.data_dir,
            config=self.config,
            session=self.session,
            token_ref=token_ref,
            token_data=token_data,
        )

    def url(self, config_key: str, path: str) -> str:
        """Build an API URL from ``config["urls"]`` and a path."""

        base = str(self.config.get("urls", {}).get(config_key, "")).rstrip("/")
        suffix = path if path.startswith("/") else f"/{path}"
        return f"{base}{suffix}"

    def auth_headers(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        """Add OAuth Authorization when this context is token-bound."""

        merged = dict(headers or {})
        if self.token_ref is not None:
            merged["Authorization"] = f"OAuth {self.token_ref.token}"
        return merged


def _clean_scopes(scopes: Any) -> set[str]:
    """Normalize a scope list into a non-empty string set."""
    if not isinstance(scopes, list):
        return set()
    return {str(scope).strip() for scope in scopes if str(scope).strip()}


def _catalog(config: dict[str, Any]) -> dict[str, Any]:
    """Return the OAuth app catalog object from merged config."""
    raw = config.get("oauth_apps", {}).get("catalog", {})
    return raw if isinstance(raw, dict) else {}


def _app_for_client_id(config: dict[str, Any], client_id: str) -> dict[str, Any] | None:
    """Find the configured OAuth app entry for a client id."""
    normalized = str(client_id).strip()
    for raw in _catalog(config).values():
        if isinstance(raw, dict) and str(raw.get("client_id", "")).strip() == normalized:
            return raw
    return None


def _validate_auth_shape(method_id: str, public: bool, one_of: Any, all_of: Any) -> MethodAuth:
    """Validate and normalize decorator auth metadata."""
    one = tuple(str(scope).strip() for scope in one_of or [] if str(scope).strip())
    all_scopes = tuple(str(scope).strip() for scope in all_of or [] if str(scope).strip())
    shape_count = sum([bool(public), bool(one), bool(all_scopes)])
    if shape_count != 1:
        raise ValueError(
            f"{method_id} must declare exactly one auth shape: public, one_of, or all_of"
        )
    return MethodAuth(
        method_id=method_id,
        public=bool(public),
        one_of=one,
        all_of=all_scopes,
    )


def yandex_api_method(
    method_id: str,
    *,
    public: bool = False,
    one_of: list[str] | tuple[str, ...] | None = None,
    all_of: list[str] | tuple[str, ...] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Wrap an actually used API method with method-aware auth dispatch."""

    auth = _validate_auth_shape(method_id, public, one_of, all_of)

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        """Attach auth metadata and dispatch decorated calls."""
        setattr(func, "_yandex_api_method", auth)

        @functools.wraps(func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            """Dispatch one decorated API call through managed auth."""
            invocation = _decorated_invocation(func, args, kwargs)
            if invocation is None:
                return func(*args, **kwargs)
            ctx, invoke = invocation
            return _dispatch_yandex_api(invoke, auth, ctx)

        setattr(wrapped, "_yandex_api_method", auth)
        setattr(wrapped, "_yandex_api_original", func)
        setattr(wrapped, "__yandex_method_id__", method_id)
        setattr(wrapped, "__yandex_auth__", auth.requirement())
        return wrapped

    return decorate


def method_auth(func: Callable[..., Any]) -> MethodAuth:
    """Return decorator metadata from a function or bound method."""

    target = getattr(func, "__func__", func)
    auth = getattr(target, "_yandex_api_method", None)
    if not isinstance(auth, MethodAuth):
        raise TypeError(f"{getattr(target, '__name__', target)!r} is not a yandex API method")
    return auth


def _decorated_invocation(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple[YandexApiContext, Callable[[YandexApiContext], Any]] | None:
    """Resolve context and original-call closure for an active decorator.

    Protocol methods that still receive explicit credentials are decorated for
    audit, but cannot enter this dispatcher until they expose a request context.
    """

    if not args:
        ctx = kwargs.get("ctx")
        if isinstance(ctx, YandexApiContext):
            return ctx, lambda request_ctx: func(**{**kwargs, "ctx": request_ctx})
        return None

    first = args[0]
    if isinstance(first, YandexApiContext):
        call_args = args[1:]
        return first, lambda request_ctx: func(request_ctx, *call_args, **kwargs)

    if len(args) > 1 and isinstance(args[1], YandexApiContext):
        owner = first
        call_args = args[2:]
        return args[1], lambda request_ctx: func(owner, request_ctx, *call_args, **kwargs)

    kw_ctx = kwargs.get("ctx")
    if isinstance(kw_ctx, YandexApiContext):
        return kw_ctx, lambda request_ctx: func(*args, **{**kwargs, "ctx": request_ctx})

    api_context = getattr(first, "_api_context", None)
    if callable(api_context):
        owner = first
        call_args = args[1:]
        ctx = api_context()
        return ctx, lambda request_ctx: func(owner, request_ctx, *call_args, **kwargs)

    return None


def _token_matches(auth: MethodAuth, app_scopes: set[str]) -> bool:
    """Return whether an app scope set satisfies method auth."""
    if auth.public:
        return True
    if auth.one_of:
        return bool(app_scopes.intersection(auth.one_of))
    return set(auth.all_of).issubset(app_scopes)


def _ordered_refs(refs: list[TokenRef]) -> list[TokenRef]:
    """Prefer latest known-good tokens, then neutral tokens; skip bad tokens."""

    good = sorted(
        (ref for ref in refs if ref.good_at),
        key=lambda ref: ref.good_at or "",
        reverse=True,
    )
    neutral = [ref for ref in refs if not ref.good_at and not ref.bad_at]
    return good + neutral


def candidate_tokens(
    *,
    auth: MethodAuth,
    token_data: dict[str, Any],
    config: dict[str, Any],
) -> list[TokenRef]:
    """Return eligible token candidates for a decorated method."""

    if auth.public:
        return []

    candidates: list[TokenRef] = []
    for ref in token_refs(token_data):
        app = _app_for_client_id(config, ref.client_id)
        if app is None:
            raise TokenConfigError(
                f"Token references client_id missing from app config: {ref.client_id}"
            )
        if _token_matches(auth, _clean_scopes(app.get("scopes"))):
            candidates.append(ref)
    return _ordered_refs(candidates)


def _agent_catalog_entry(config: dict[str, Any], app_id: str) -> dict[str, Any] | None:
    """Return one agent-local OAuth app entry if present."""
    raw = _catalog(config).get(app_id)
    return raw if isinstance(raw, dict) else None


def _merge_agent_oauth_app(
    config: dict[str, Any],
    *,
    app_id: str,
    app_entry: dict[str, Any],
) -> None:
    """Merge one OAuth app entry into runtime config."""
    apps = config.setdefault("oauth_apps", {})
    if not isinstance(apps, dict):
        raise TokenConfigError("oauth_apps must be an object")
    catalog = apps.setdefault("catalog", {})
    if not isinstance(catalog, dict):
        raise TokenConfigError("oauth_apps.catalog must be an object")
    catalog[app_id] = dict(app_entry)


def _upgrade_missing_client_apps(
    ctx: YandexApiContext,
    *,
    token_data: dict[str, Any],
) -> None:
    """Promote unknown token client_ids into agent-local app config.

    GH41 makes token files the account inventory, but app scopes remain
    config-backed. When an already-verified token references a client_id that
    the merged catalog does not know, the automatic upgrade path verifies the
    token binding, resolves Yandex's app metadata, persists an agent-local app,
    and only then allows decorator eligibility to decide whether it can be used.
    """

    missing_refs = [
        ref
        for ref in token_refs(token_data)
        if _app_for_client_id(ctx.config, ref.client_id) is None
    ]
    if not missing_refs:
        return

    agent_config_path, agent_config = load_agent_config_payload(ctx.data_dir)
    for ref in missing_refs:
        try:
            identity = verify_token_identity(ctx.config, token=ref.token)
        except RuntimeError as exc:
            raise TokenConfigError(
                f"Cannot upgrade token client_id {ref.client_id}: token verification failed"
            ) from exc

        if identity.client_id != ref.client_id:
            raise TokenConfigError(
                f"Cannot upgrade token client_id {ref.client_id}: verified client_id "
                f"{identity.client_id} does not match token file"
            )

        expected_email = str(token_data.get("email") or "").strip()
        if expected_email and identity.email.lower() != expected_email.lower():
            raise TokenConfigError(
                f"Cannot upgrade token client_id {ref.client_id}: verified email "
                f"{identity.email} does not match token file email {expected_email}"
            )

        try:
            metadata = fetch_yandex_oauth_client_metadata(
                ctx.config,
                client_id=ref.client_id,
            )
        except (RuntimeError, ValueError) as exc:
            raise TokenConfigError(
                f"Cannot upgrade token client_id {ref.client_id}: OAuth app metadata lookup failed"
            ) from exc

        app_id = upsert_agent_oauth_app(
            agent_config,
            client_id=metadata.client_id,
            scopes=metadata.scopes,
            app_name=metadata.app_name,
        )
        app_entry = _agent_catalog_entry(agent_config, app_id)
        if app_entry is None:
            raise TokenConfigError(
                f"Cannot upgrade token client_id {ref.client_id}: agent app upsert failed"
            )
        _merge_agent_oauth_app(ctx.config, app_id=app_id, app_entry=app_entry)

    save_agent_config_payload(agent_config_path, agent_config)


def method_client_ids(*, auth: MethodAuth, config: dict[str, Any]) -> list[str]:
    """Derive configured client ids that can satisfy a method auth shape."""

    if auth.public:
        return []
    client_ids: list[str] = []
    for raw in _catalog(config).values():
        if not isinstance(raw, dict):
            continue
        client_id = str(raw.get("client_id", "")).strip()
        if client_id and _token_matches(auth, _clean_scopes(raw.get("scopes"))):
            client_ids.append(client_id)
    return sorted(set(client_ids))


def authorization_urls(*, auth: MethodAuth, config: dict[str, Any]) -> list[str]:
    """Build end-user authorization URLs for configured apps that match auth."""

    urls: list[str] = []
    for raw in _catalog(config).values():
        if not isinstance(raw, dict):
            continue
        scopes = sorted(_clean_scopes(raw.get("scopes")))
        client_id = str(raw.get("client_id", "")).strip()
        if not client_id or not _token_matches(auth, set(scopes)):
            continue
        urls.append(
            build_approval_url(
                config,
                client_id=client_id,
                scopes=scopes,
                include_scope=not bool(raw.get("omit_scope_in_url", True)),
            )
        )
    return urls


def _timestamp() -> str:
    """Return the current UTC timestamp in token-state format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _mark_token(token_data: dict[str, Any], token_ref: TokenRef, *, good: bool) -> None:
    """Mark one token candidate as good or bad."""
    entry = token_data.get(token_ref.source_key)
    if not isinstance(entry, dict):
        entry = {"client_id": token_ref.client_id}
    entry.pop("good_at", None)
    entry.pop("bad_at", None)
    entry["good_at" if good else "bad_at"] = _timestamp()
    token_data[token_ref.source_key] = entry


def _provider_payload(response: requests.Response) -> tuple[Any, str | None, str]:
    """Extract provider payload, error name, and display message."""
    try:
        payload = response.json()
    except ValueError:
        text = response.text[:500]
        return None, None, text or f"HTTP {response.status_code}"

    provider_error = None
    message = ""
    if isinstance(payload, dict):
        provider_error = str(payload.get("error") or payload.get("error_name") or "").strip() or None
        message = str(
            payload.get("message")
            or payload.get("description")
            or payload.get("error_description")
            or provider_error
            or f"HTTP {response.status_code}"
        )
    else:
        message = f"HTTP {response.status_code}"
    return payload, provider_error, message


def _raise_provider_error(response: requests.Response) -> None:
    """Raise the shared provider exception for one response."""
    payload, provider_error, message = _provider_payload(response)
    error_cls = (
        TokenRejected
        if response.status_code == 403 and provider_error == "ForbiddenError"
        else YandexApiError
    )
    raise error_cls(
        provider_error=provider_error,
        status_code=response.status_code,
        message=message,
        payload=payload,
    )


def handle_json_response(
    response: requests.Response,
    *,
    expected_statuses: tuple[int, ...] = (200,),
) -> Any:
    """Return JSON payload or raise the central GH41 provider exception."""

    if response.status_code in expected_statuses:
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise YandexApiError(
                provider_error=None,
                status_code=response.status_code,
                message="Yandex API returned invalid JSON",
                payload=response.text[:500],
            ) from exc

    _raise_provider_error(response)


def handle_response(
    response: requests.Response,
    *,
    expected_statuses: tuple[int, ...] = (200,),
) -> requests.Response:
    """Return a non-JSON response or raise the central GH41 provider exception."""

    if response.status_code in expected_statuses:
        return response

    _raise_provider_error(response)


def request_json(
    ctx: YandexApiContext,
    method: str,
    url: str,
    *,
    expected_statuses: tuple[int, ...] = (200,),
    return_status: bool = False,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> Any:
    """Send a JSON-oriented HTTP request with context-bound OAuth headers."""

    response = ctx.session.request(
        method,
        url,
        headers=ctx.auth_headers(headers),
        **kwargs,
    )
    payload = handle_json_response(response, expected_statuses=expected_statuses)
    if return_status:
        return payload, response.status_code
    return payload


def _resolve_account_alias(ctx: YandexApiContext, method_id: str) -> str:
    """Resolve the token-file account alias for a non-public decorated method."""

    if ctx.account:
        return ctx.account

    auth_dir = ctx.data_dir / "auth"
    token_paths = sorted(auth_dir.glob("*.token")) if auth_dir.exists() else []
    if len(token_paths) == 1:
        return token_paths[0].stem
    if not token_paths:
        raise TokenConfigError(
            f"Account is required for {method_id}: no token files found"
        )
    aliases = ", ".join(path.stem for path in token_paths)
    raise TokenConfigError(
        f"Account is required for {method_id}: multiple token files found ({aliases})"
    )


def _legacy_disk_env_token() -> str | None:
    """Return the legacy Disk env token value when present."""

    token = os.environ.get(LEGACY_DISK_TOKEN_ENV, "").strip()
    return token or None


def digest_legacy_disk_token_env(ctx: YandexApiContext) -> None:
    """Run the managed env-token import path for legacy Disk compatibility."""

    token = _legacy_disk_env_token()
    if not token:
        return

    auth_dir = ctx.data_dir / "auth"
    token_paths = (
        [auth_dir / f"{ctx.account}.token"]
        if ctx.account
        else sorted(auth_dir.glob("*.token")) if auth_dir.exists() else []
    )
    for token_path in token_paths:
        try:
            if token in load_token_file(token_path):
                return
        except FileNotFoundError:
            pass

    agent_config_path, agent_config = load_agent_config_payload(ctx.data_dir)
    import_managed_oauth_token(
        config=ctx.config,
        data_dir=ctx.data_dir,
        agent_config=agent_config,
        agent_config_path=agent_config_path,
        token=token,
        account=ctx.account,
        service="disk",
        account_context_only=True,
    )


def _load_token_data_for_dispatch(
    ctx: YandexApiContext,
    *,
    account: str,
    token_path: Path,
) -> dict[str, Any]:
    """Load token data for the selected account."""

    try:
        return load_prepared_token_file(token_path, ctx.config)
    except FileNotFoundError:
        raise TokenConfigError(
            f"Token file not found for account {account}: {token_path}"
        )


def _dispatch_yandex_api(
    invoke: Callable[[YandexApiContext], Any],
    auth: MethodAuth,
    ctx: YandexApiContext,
) -> Any:
    """Execute the GH41 token loop for one decorated API method invocation."""

    if auth.public:
        return invoke(ctx)

    if auth.method_id.startswith("disk."):
        try:
            digest_legacy_disk_token_env(ctx)
        except Exception:
            pass

    account = _resolve_account_alias(ctx, auth.method_id)
    token_path = ctx.data_dir / "auth" / f"{account}.token"
    token_data = _load_token_data_for_dispatch(
        ctx,
        account=account,
        token_path=token_path,
    )
    _upgrade_missing_client_apps(ctx, token_data=token_data)
    candidates = candidate_tokens(auth=auth, token_data=token_data, config=ctx.config)
    if not candidates:
        _upgrade_missing_client_apps(ctx, token_data=token_data)
        candidates = candidate_tokens(auth=auth, token_data=token_data, config=ctx.config)
    dispatch_ctx = (
        ctx
        if ctx.account == account
        else YandexApiContext(
            account=account,
            data_dir=ctx.data_dir,
            config=ctx.config,
            session=ctx.session,
        )
    )

    for token_ref in candidates:
        token_ctx = dispatch_ctx.for_token(
            token_ref,
            token_path=token_path,
            token_data=token_data,
        )
        try:
            result = invoke(token_ctx)
        except TokenRejected:
            _mark_token(token_data, token_ref, good=False)
            save_token_file(token_path, token_data)
            continue
        except Exception:
            # Non-auth failures are business/API failures. Do not poison the token
            # and do not mark it good: the method did not complete normally.
            raise
        _mark_token(token_data, token_ref, good=True)
        save_token_file(token_path, token_data)
        return result

    raise BlockedYandexMethodError(
        f"No usable token completed {auth.method_id}",
        method_id=auth.method_id,
        required=auth.requirement(),
        client_ids=method_client_ids(auth=auth, config=ctx.config),
        authorization_urls=authorization_urls(auth=auth, config=ctx.config),
    )
