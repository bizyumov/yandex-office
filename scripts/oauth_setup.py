#!/usr/bin/env python3
"""
Yandex OAuth token setup.

Generates per-account OAuth tokens and stores the verified token-value to
client_id binding used by the shared Yandex auth resolver.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.auth import load_token_file, save_token_file, token_refs
from common.config import bootstrap_runtime_context, choose_account_alias, find_token_account_by_email
from common.oauth_apps import (
    oauth_app_for_client_id,
    plan_oauth_app_setup,
)
from common.oauth_token_import import import_managed_oauth_token


OAUTH_SCREEN_CODE_REDIRECT_URI = "https://oauth.yandex.ru/verification_code"
OAUTH_CODE_FLOW_PENDING_TTL_SECONDS = 600


def _read_access_token(prompt: str) -> str:
    """Read an OAuth access token without echoing it."""
    return getpass.getpass(prompt)


def _print_warnings(warnings: list[str]) -> None:
    """Print warning lines to stderr."""
    if warnings:
        print("Warnings:", file=sys.stderr)
        for warning in warnings:
            print(f"  - {warning}", file=sys.stderr)


def _format_custom_app(scopes: list[str]) -> str:
    """Return the compact label for a non-shipped OAuth app."""
    return f"custom({', '.join(scopes)})" if scopes else "custom()"


def _urlsafe_b64(data: bytes) -> str:
    """Return unpadded URL-safe base64."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _validate_code_flow_app_id(app_id: str) -> str:
    """Return a safe configured app id for registry keys."""
    normalized = str(app_id).strip()
    if not normalized or Path(normalized).name != normalized:
        raise ValueError("--app must be a plain configured app id")
    return normalized


def _code_flow_registry_path(data_dir: Path) -> Path:
    """Return the single registry file for all pending screen-code flows."""
    return data_dir / "auth" / "oauth-code-flow.json"


def _load_code_flow_registry(data_dir: Path) -> dict[str, list[dict[str, object]]]:
    """Load the ordered pending screen-code registry."""
    registry_path = _code_flow_registry_path(data_dir)
    try:
        with open(registry_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {"pending": []}
    if not isinstance(payload, dict):
        raise RuntimeError("Pending code-flow registry is invalid")
    raw_pending = payload.get("pending", [])
    if not isinstance(raw_pending, list):
        raise RuntimeError("Pending code-flow registry pending list is invalid")
    pending = [dict(item) for item in raw_pending if isinstance(item, dict)]
    return {"pending": pending}


def _save_code_flow_registry(data_dir: Path, registry: dict[str, list[dict[str, object]]]) -> Path:
    """Persist the ordered pending screen-code registry atomically."""
    registry_path = _code_flow_registry_path(data_dir)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = registry_path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump({"pending": registry.get("pending", [])}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temp_path.replace(registry_path)
    registry_path.chmod(0o600)
    return registry_path


def _next_unique_created_at(registry: dict[str, list[dict[str, object]]]) -> int:
    """Return a strictly increasing issued timestamp for registry order."""
    now = int(time.time())
    existing = [int(str(item.get("created_at") or 0)) for item in registry.get("pending", [])]
    last = max(existing, default=0)
    return max(now, last + 1)


def _write_pending_code_flow(
    data_dir: Path,
    *,
    app_id: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
    state: str,
    account: str | None,
    email: str | None,
) -> Path:
    """Append pending PKCE state in the exact order links are issued."""
    app_id = _validate_code_flow_app_id(app_id)
    registry = _load_code_flow_registry(data_dir)
    created_at = _next_unique_created_at(registry)
    payload = {
        "app_id": app_id,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "state": state,
        "created_at": created_at,
        "expires_at": created_at + OAUTH_CODE_FLOW_PENDING_TTL_SECONDS,
    }
    if account:
        payload["account"] = account
    if email:
        payload["email"] = email
    registry.setdefault("pending", []).append(payload)
    return _save_code_flow_registry(data_dir, registry)


def _remove_pending_code_flow_at_index(data_dir: Path, *, index: int) -> Path:
    """Remove one completed pending flow by issued-order index."""
    registry = _load_code_flow_registry(data_dir)
    pending = registry.get("pending", [])
    if 0 <= index < len(pending):
        pending.pop(index)
    return _save_code_flow_registry(data_dir, {"pending": pending})


def _unexpired_pending_code_flows(data_dir: Path) -> list[tuple[int, dict[str, object]]]:
    """Return unexpired pending flows in the exact link issue order."""
    registry = _load_code_flow_registry(data_dir)
    now = int(time.time())
    kept: list[dict[str, object]] = []
    result: list[tuple[int, dict[str, object]]] = []
    for item in registry.get("pending", []):
        expires_at = int(str(item.get("expires_at") or 0))
        if expires_at and expires_at < now:
            continue
        kept.append(item)
        result.append((len(kept) - 1, item))
    if len(kept) != len(registry.get("pending", [])):
        _save_code_flow_registry(data_dir, {"pending": kept})
    return result


def _build_code_flow_authorization_url(
    config: dict[str, object],
    *,
    plan,
    code_challenge: str,
    state: str,
    email: str | None,
) -> str:
    """Build a Yandex screen-code authorization URL with PKCE."""
    oauth_base = config.get("urls", {}).get(
        "oauth",
        "https://oauth.yandex.ru/authorize",
    )
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": plan.client_id,
        "redirect_uri": OAUTH_SCREEN_CODE_REDIRECT_URI,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "force_confirm": "yes",
    }
    if email:
        params["login_hint"] = email
    if plan.include_scope_in_url and plan.scopes:
        params["scope"] = " ".join(sorted(set(plan.scopes)))
    return f"{oauth_base}?{urlencode(params)}"


def _start_code_flow(
    *,
    config: dict[str, object],
    data_dir: Path,
    plan,
    account: str | None,
    email: str | None,
) -> Path:
    """Create pending PKCE state and print the screen-code URL."""
    code_verifier = _urlsafe_b64(secrets.token_bytes(48))
    code_challenge = _urlsafe_b64(hashlib.sha256(code_verifier.encode("ascii")).digest())
    state = secrets.token_urlsafe(24)
    auth_url = _build_code_flow_authorization_url(
        config,
        plan=plan,
        code_challenge=code_challenge,
        state=state,
        email=email,
    )
    pending_path = _write_pending_code_flow(
        data_dir,
        app_id=plan.app_id,
        client_id=plan.client_id,
        redirect_uri=OAUTH_SCREEN_CODE_REDIRECT_URI,
        code_verifier=code_verifier,
        state=state,
        account=account,
        email=email,
    )
    pending_items = _load_code_flow_registry(data_dir)["pending"]
    pending = pending_items[-1]
    expires_at = int(str(pending["expires_at"]))
    expires_at_text = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()
    display_account = account or "<auto>"
    print("=" * 70)
    print(f"Yandex OAuth Screen-Code Setup — {display_account}")
    print("=" * 70)
    print(f"App ID:  {plan.app_id}")
    if plan.app_name:
        print(f"App:     {plan.app_name}")
    print(f"Client:  {plan.client_id}")
    print("\nInstructions:")
    print("  1. Open the URL below in your browser")
    print("  2. Log in with your Yandex account")
    print("  3. Grant the requested permissions")
    print("  4. Copy the short confirmation code shown by Yandex")
    print("  5. Run --code-flow complete --code <confirmation-code>")
    print("\nCode lifetime: 10 minutes")
    print("Check order: links are tried in the order printed")
    print(f"Expires at: {expires_at_text}")
    print(f"\nAuthorization URL:\n\n  {auth_url}\n")
    print(f"Pending registry: {pending_path}")
    print("=" * 70)
    return pending_path


def _exchange_authorization_code_for_token(
    *,
    config: dict,
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, object]:
    """Exchange a Yandex screen confirmation code for OAuth token JSON."""
    token_url = config.get("urls", {}).get("oauth_token", "https://oauth.yandex.ru/token")
    body = urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
    ).encode("utf-8")
    request = Request(
        token_url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=20.0) as response:
            payload = json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Yandex authorization-code exchange failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Yandex authorization-code exchange failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Yandex authorization-code exchange returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Yandex authorization-code exchange returned non-object JSON")
    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("Yandex authorization-code exchange did not return access_token")
    return payload


def _account_apps(config: dict[str, object], token_data: dict[str, object]) -> list[str]:
    """Return configured app labels present in an account token file."""
    apps: set[str] = set()
    for ref in token_refs(token_data):
        app = oauth_app_for_client_id(config, ref.client_id)
        if app is None:
            apps.add("custom()")
        elif app.app_id.startswith("custom-") or not app.services:
            apps.add(_format_custom_app(app.scopes))
        else:
            apps.add(app.app_id)
    return sorted(apps)


def _print_account_info(
    alias: str,
    token_data: dict[str, object],
    *,
    config: dict[str, object],
) -> None:
    """Print compact account summary JSON."""
    info: dict[str, object] = {"alias": alias}
    email = str(token_data.get("email") or "").strip()
    if email:
        info["email"] = email
    info["apps"] = _account_apps(config, token_data)
    print(json.dumps(info, ensure_ascii=False, separators=(",", ":")))


def main() -> None:
    """Run the Yandex OAuth setup command-line interface."""
    parser = argparse.ArgumentParser(
        description="Bootstrap Yandex data dir or set up OAuth app managed auth",
    )
    parser.add_argument("--email", help="Yandex email address")
    parser.add_argument(
        "--account",
        help="Account alias used as token filename",
    )
    parser.add_argument(
        "--accounts",
        choices=("list", "delete", "reset"),
        help="Manage token-file account aliases",
    )
    parser.add_argument(
        "--app",
        help="Preconfigured OAuth app id to authorize",
    )
    parser.add_argument(
        "--data-dir",
        help="Explicit Yandex data directory override for non-CWD execution",
    )
    parser.add_argument(
        "--from-env",
        metavar="ENV_VAR",
        help="Import an environment OAuth token into managed auth",
    )
    parser.add_argument(
        "--code-flow",
        choices=("start", "complete"),
        help="Use Yandex screen-code authorization flow with PKCE",
    )
    parser.add_argument(
        "--code",
        help="Short Yandex confirmation code for --code-flow complete",
    )
    args = parser.parse_args()

    if args.from_env:
        args.from_env = args.from_env.strip()
        if not args.from_env:
            parser.error("--from-env requires an environment variable name")

    has_oauth_args = (
        args.app is not None
        or args.from_env is not None
        or args.code_flow is not None
    )
    if args.accounts and (args.email is not None or has_oauth_args):
        parser.error("--accounts cannot be combined with OAuth setup arguments")
    if args.accounts == "delete" and args.account is None:
        parser.error("--accounts delete requires --account <alias>")
    if args.accounts in {"list", "reset"} and args.account is not None:
        parser.error(f"--accounts {args.accounts} does not use --account")
    if args.code and args.code_flow != "complete":
        parser.error("--code requires --code-flow complete")
    if args.code_flow and args.from_env:
        parser.error("--code-flow cannot be combined with --from-env")
    if args.code_flow == "start" and args.app is None:
        parser.error("--code-flow start requires --app <app_id>")
    if args.code_flow == "complete" and not str(args.code or "").strip():
        parser.error("--code-flow complete requires --code <confirmation-code>")

    runtime = bootstrap_runtime_context(
        __file__,
        account=None if args.accounts else args.account,
        email=args.email,
        cwd=Path.cwd(),
        data_dir_override=args.data_dir,
    )
    config = runtime.config
    data_dir = runtime.data_dir

    if args.accounts:
        token_paths = sorted((data_dir / "auth").glob("*.token"))
        if args.accounts == "list":
            for token_path in token_paths:
                print(token_path.stem)
            return
        if args.accounts == "reset":
            for token_path in token_paths:
                token_path.unlink()
            print(f"reset {len(token_paths)}")
            return
        alias = str(args.account or "").strip()
        if not alias or Path(alias).name != alias:
            parser.error("--accounts delete requires a plain --account <alias>")
        token_path = data_dir / "auth" / f"{alias}.token"
        if not token_path.exists():
            print(f"missing {alias}", file=sys.stderr)
            sys.exit(2)
        token_path.unlink()
        print(f"deleted {alias}")
        return

    has_identity_args = any(value is not None for value in (args.email, args.account))

    if not has_identity_args and not has_oauth_args:
        print(data_dir)
        return

    if not has_oauth_args:
        normalized_email = str(args.email or "").strip()
        requested_account = str(args.account or "").strip()
        existing_account = None if requested_account else (
            find_token_account_by_email(data_dir, normalized_email)
            if normalized_email
            else None
        )
        if requested_account:
            resolved_account = requested_account
        elif existing_account is not None:
            resolved_account = existing_account["alias"]
        elif normalized_email:
            resolved_account = choose_account_alias(
                data_dir,
                normalized_email,
                preferred_name=requested_account or None,
            )
        else:
            resolved_account = requested_account
        if not resolved_account or Path(resolved_account).name != resolved_account:
            parser.error("--account must be a plain alias")

        token_path = data_dir / "auth" / f"{resolved_account}.token"
        try:
            token_data = load_token_file(token_path)
        except FileNotFoundError:
            token_data = {}
        if normalized_email:
            token_data["email"] = normalized_email
        save_token_file(token_path, token_data)

        _print_account_info(resolved_account, token_data, config=config)
        return

    if args.code_flow:
        if args.code_flow == "start":
            try:
                plan = plan_oauth_app_setup(config, app_id=str(args.app))
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(2)
            _start_code_flow(
                config=config,
                data_dir=data_dir,
                plan=plan,
                account=args.account,
                email=args.email,
            )
            return
        try:
            code = str(args.code or "").strip()
            import_result = None
            matched_index = None
            last_error = None
            pending_candidates = _unexpired_pending_code_flows(data_dir)
            if not pending_candidates:
                raise RuntimeError("No pending code-flow authorizations. Run --code-flow start first.")
            for index, pending in pending_candidates:
                app_id = str(pending.get("app_id") or "").strip()
                try:
                    token_payload = _exchange_authorization_code_for_token(
                        config=config,
                        code=code,
                        client_id=str(pending.get("client_id") or ""),
                        redirect_uri=str(pending.get("redirect_uri") or OAUTH_SCREEN_CODE_REDIRECT_URI),
                        code_verifier=str(pending.get("code_verifier") or ""),
                    )
                except RuntimeError as exc:
                    if "bad_verification_code" in str(exc) or "Invalid code" in str(exc):
                        last_error = exc
                        continue
                    raise
                token = str(token_payload.get("access_token") or "").strip()
                import_result = import_managed_oauth_token(
                    config=config,
                    data_dir=data_dir,
                    agent_config=runtime.agent_config,
                    agent_config_path=runtime.agent_config_path,
                    token=token,
                    email=args.email,
                    account=args.account,
                    selected_app_id=app_id or None,
                )
                matched_index = index
                break
            if import_result is None or matched_index is None:
                detail = f": {last_error}" if last_error else ""
                raise RuntimeError(f"Confirmation code did not match any pending authorization{detail}")
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        _remove_pending_code_flow_at_index(data_dir, index=matched_index)
        _print_warnings(import_result.warnings)
        print(import_result.resolved_account)
        return

    has_oauth_selector = (
        args.app is not None
    )
    plan = None
    if not (args.from_env and not has_oauth_selector):
        try:
            plan = plan_oauth_app_setup(config, app_id=args.app)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)

    if not args.from_env:
        display_account = args.account or "<auto>"
        print("=" * 70)
        print(f"Yandex OAuth Managed Auth Setup — {display_account}")
        print("=" * 70)
        print(f"\nAccount: {display_account}")

        print(f"Mode:    {plan.mode if plan is not None else 'env_import'}")
        if plan is not None:
            if plan.app_id:
                print(f"App ID:  {plan.app_id}")
            if plan.app_name:
                print(f"App:     {plan.app_name}")
            print(f"Client:  {plan.client_id}")
            print(f"Scope:   {' '.join(plan.scopes) if plan.scopes else '(none)'}")
        print("\nInstructions:")
        print("  1. Open the URL below in your browser")
        print("  2. Log in with your Yandex account")
        print("  3. Grant the requested permissions")
        print("  4. Copy the access_token from the redirect URL")
        if plan is not None and plan.mode == "configured_app" and not plan.include_scope_in_url:
            print("  Note: this URL relies on the OAuth app's baked-in scope set")
        if plan is not None:
            print(f"\nAuthorization URL:\n\n  {plan.auth_url}\n")
        print("=" * 70)

    if args.from_env:
        token = os.environ.get(args.from_env, "").strip()
        if not token:
            print("Error: Environment variable is empty or unset", file=sys.stderr)
            sys.exit(1)
    else:
        token = _read_access_token("\nPaste the access_token here: ").strip()
    if not token:
        print("Error: Token cannot be empty", file=sys.stderr)
        sys.exit(1)

    try:
        import_result = import_managed_oauth_token(
            config=config,
            data_dir=data_dir,
            agent_config=runtime.agent_config,
            agent_config_path=runtime.agent_config_path,
            token=token,
            email=args.email,
            account=args.account,
            selected_app_id=plan.app_id if plan is not None else None,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    warnings = import_result.warnings
    _print_warnings(warnings)
    print(import_result.resolved_account)


if __name__ == "__main__":
    main()
