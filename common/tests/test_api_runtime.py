from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.api import (
    TokenConfigError,
    TokenRejected,
    YandexApiContext,
    YandexApiError,
    candidate_tokens,
    handle_json_response,
    method_auth,
    yandex_api_method,
)
import common.api as api_module
import common.auth as auth_module
from common.auth import VerifiedTokenIdentity
from common.oauth_apps import OAuthClientMetadata
import common.oauth_token_import as token_import


@pytest.fixture(autouse=True)
def _bridge_token_import_verify(monkeypatch) -> None:
    monkeypatch.setattr(
        token_import,
        "verify_token_identity",
        lambda *args, **kwargs: api_module.verify_token_identity(*args, **kwargs),
    )


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""
        self.content = self.text.encode("utf-8")

    def json(self):
        if self._payload is None:
            raise ValueError("No JSON")
        return self._payload


class FakeSession:
    def request(self, *args, **kwargs):  # pragma: no cover - public bypass asserts no call
        raise AssertionError("request should not be called")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def config() -> dict:
    return {
        "urls": {"oauth": "https://oauth.yandex.ru/authorize"},
        "oauth_apps": {
            "catalog": {
                "read": {
                    "client_id": "client-read",
                    "scopes": ["scope:read"],
                },
                "write": {
                    "client_id": "client-write",
                    "scopes": ["scope:read", "scope:write"],
                },
            },
        },
    }


def context(tmp_path: Path, account: str | None = "acct") -> YandexApiContext:
    return YandexApiContext(
        account=account,
        data_dir=tmp_path,
        config=config(),
        session=FakeSession(),
    )


def test_public_method_bypasses_token_file(tmp_path: Path) -> None:
    @yandex_api_method("demo.public", public=True)
    def public_method(ctx: YandexApiContext) -> str:
        assert ctx.token_ref is None
        return "ok"

    result = public_method(context(tmp_path))

    assert result == "ok"
    assert not (tmp_path / "auth" / "acct.token").exists()


def test_candidate_tokens_support_one_of_and_all_of() -> None:
    token_data = {
        "email": "user@example.com",
        "read-token": {"client_id": "client-read"},
        "write-token": {"client_id": "client-write"},
    }

    @yandex_api_method("demo.one", one_of=["scope:write"])
    def one(ctx):
        return None

    @yandex_api_method("demo.all", all_of=["scope:read", "scope:write"])
    def all_required(ctx):
        return None

    one_candidates = candidate_tokens(
        auth=method_auth(one),
        token_data=token_data,
        config=config(),
    )
    all_candidates = candidate_tokens(
        auth=method_auth(all_required),
        token_data=token_data,
        config=config(),
    )

    assert [item.token for item in one_candidates] == ["write-token"]
    assert [item.token for item in all_candidates] == ["write-token"]


def test_candidate_tokens_skip_bad_tokens_and_prefer_latest_good() -> None:
    token_data = {
        "email": "user@example.com",
        "old-good-token": {
            "client_id": "client-read",
            "good_at": "2026-04-23T20:00:00Z",
        },
        "bad-token": {
            "client_id": "client-read",
            "bad_at": "2026-04-23T21:00:00Z",
        },
        "new-good-token": {
            "client_id": "client-read",
            "good_at": "2026-04-23T22:00:00Z",
        },
        "neutral-token": {"client_id": "client-read"},
    }

    @yandex_api_method("demo.read", one_of=["scope:read"])
    def method(ctx):
        return None

    candidates = candidate_tokens(
        auth=method_auth(method),
        token_data=token_data,
        config=config(),
    )

    assert [item.token for item in candidates] == [
        "new-good-token",
        "old-good-token",
        "neutral-token",
    ]


def test_dispatch_auto_upgrades_unknown_client_id_from_oauth_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    write_json(
        tmp_path / "auth" / "acct.token",
        {
            "email": "user@example.com",
            "cloud-token": {"client_id": "cloud-client"},
            "read-token": {"client_id": "client-read"},
        },
    )
    attempts = []

    def fake_verify(_config: dict, *, token: str) -> VerifiedTokenIdentity:
        assert token == "cloud-token"
        return VerifiedTokenIdentity(
            email="user@example.com",
            client_id="cloud-client",
        )

    def fake_metadata(
        _config: dict,
        *,
        client_id: str,
    ) -> OAuthClientMetadata:
        assert client_id == "cloud-client"
        return OAuthClientMetadata(
            client_id="cloud-client",
            app_name="Yandex.Cloud",
            scopes=["cloud:auth"],
    )

    monkeypatch.setattr(api_module, "verify_token_identity", fake_verify)
    monkeypatch.setattr(
        api_module,
        "fetch_yandex_oauth_client_metadata",
        fake_metadata,
    )

    @yandex_api_method("demo.read", one_of=["scope:read"])
    def method(ctx: YandexApiContext) -> str:
        attempts.append(ctx.token_ref.token)
        return "ok"

    runtime_config = config()
    result = method(
        YandexApiContext(
            account="acct",
            data_dir=tmp_path,
            config=runtime_config,
            session=FakeSession(),
        )
    )
    agent_config = json.loads((tmp_path / "config.agent.json").read_text())

    assert result == "ok"
    assert attempts == ["read-token"]
    assert agent_config["oauth_apps"]["catalog"]["custom-cloud-client"] == {
        "client_id": "cloud-client",
        "scopes": ["cloud:auth"],
        "name": "Yandex.Cloud",
        "omit_scope_in_url": False,
    }
    assert runtime_config["oauth_apps"]["catalog"]["custom-cloud-client"]["scopes"] == [
        "cloud:auth"
    ]


def test_dispatch_resolves_unresolved_client_id_before_use(
    tmp_path: Path,
    monkeypatch,
) -> None:
    write_json(
        tmp_path / "auth" / "acct.token",
        {
            "email": "user@example.com",
            "cloud-token": {"client_id": "cloud-client"},
        },
    )
    attempts = []

    def fake_verify(_config: dict, *, token: str) -> VerifiedTokenIdentity:
        assert token == "cloud-token"
        return VerifiedTokenIdentity(
            email="user@example.com",
            client_id="cloud-client",
        )

    def fake_metadata(
        _config: dict,
        *,
        client_id: str,
    ) -> OAuthClientMetadata:
        assert client_id == "cloud-client"
        return OAuthClientMetadata(
            client_id="cloud-client",
            app_name="Yandex.Cloud",
            scopes=["cloud:auth"],
        )

    monkeypatch.setattr(api_module, "verify_token_identity", fake_verify)
    monkeypatch.setattr(
        api_module,
        "fetch_yandex_oauth_client_metadata",
        fake_metadata,
    )

    @yandex_api_method("demo.cloud", one_of=["cloud:auth"])
    def method(ctx: YandexApiContext) -> str:
        attempts.append(ctx.token_ref.token)
        return "ok"

    runtime_config = config()
    runtime_config["oauth_apps"]["catalog"]["custom-cloud-client"] = {
        "client_id": "cloud-client",
        "scopes": ["unresolved"],
        "name": "Unresolved Yandex OAuth app cloud-cl",
        "omit_scope_in_url": False,
    }
    result = method(
        YandexApiContext(
            account="acct",
            data_dir=tmp_path,
            config=runtime_config,
            session=FakeSession(),
        )
    )
    agent_config = json.loads((tmp_path / "config.agent.json").read_text())

    assert result == "ok"
    assert attempts == ["cloud-token"]
    assert agent_config["oauth_apps"]["catalog"]["custom-cloud-client"] == {
        "client_id": "cloud-client",
        "scopes": ["cloud:auth"],
        "name": "Yandex.Cloud",
        "omit_scope_in_url": False,
    }


def test_forbidden_error_marks_bad_and_tries_next_token(tmp_path: Path) -> None:
    write_json(
        tmp_path / "auth" / "acct.token",
        {
            "email": "user@example.com",
            "bad-token": {"client_id": "client-read"},
            "good-token": {"client_id": "client-write"},
        },
    )
    attempts = []

    @yandex_api_method("demo.read", one_of=["scope:read"])
    def method(ctx: YandexApiContext) -> str:
        attempts.append(ctx.token_ref.token)
        if ctx.token_ref.token == "bad-token":
            raise TokenRejected(
                provider_error="ForbiddenError",
                status_code=403,
                message="forbidden",
            )
        return "ok"

    result = method(context(tmp_path))
    saved = json.loads((tmp_path / "auth" / "acct.token").read_text())

    assert result == "ok"
    assert attempts == ["bad-token", "good-token"]
    assert "bad_at" in saved["bad-token"]
    assert "good_at" in saved["good-token"]
    assert "good_at" not in saved["bad-token"]
    assert "bad_at" not in saved["good-token"]


def test_non_auth_failure_does_not_mark_token_good_or_bad(tmp_path: Path) -> None:
    write_json(
        tmp_path / "auth" / "acct.token",
        {
            "email": "user@example.com",
            "token": {"client_id": "client-read"},
        },
    )

    @yandex_api_method("demo.read", one_of=["scope:read"])
    def method(ctx: YandexApiContext) -> str:
        raise YandexApiError(
            provider_error="ValidationError",
            status_code=422,
            message="bad request",
        )

    with pytest.raises(YandexApiError):
        method(context(tmp_path))

    saved = json.loads((tmp_path / "auth" / "acct.token").read_text())
    assert saved["token"] == {"client_id": "client-read"}


def test_dispatch_converts_legacy_token_file_before_selecting_candidates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    write_json(
        tmp_path / "auth" / "acct.token",
        {
            "email": "old@example.com",
            "token.disk": "legacy-token",
            "token_meta": {"token.disk": {"client_id": "wrong"}},
        },
    )

    def fake_verify(config: dict, *, token: str) -> VerifiedTokenIdentity:
        assert token == "legacy-token"
        return VerifiedTokenIdentity(
            email="verified@example.com",
            client_id="client-read",
        )

    monkeypatch.setattr(auth_module, "verify_token_identity", fake_verify)

    @yandex_api_method("demo.read", one_of=["scope:read"])
    def method(ctx: YandexApiContext) -> str:
        assert ctx.token_ref.token == "legacy-token"
        return "ok"

    result = method(context(tmp_path))
    saved = json.loads((tmp_path / "auth" / "acct.token").read_text())

    assert result == "ok"
    assert saved["email"] == "verified@example.com"
    assert saved["legacy-token"]["client_id"] == "client-read"
    assert saved["legacy-token"]["good_at"]
    assert "token.disk" not in saved
    assert "token_meta" not in saved


def test_dispatch_does_not_auto_upgrade_legacy_yandex_disk_token_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("YANDEX_DISK_TOKEN", "legacy-env-token")
    monkeypatch.setattr(
        api_module,
        "verify_token_identity",
        lambda *_args, **_kwargs: VerifiedTokenIdentity(
            email="disk@example.com",
            client_id="client-read",
        ),
    )

    @yandex_api_method("disk.resources.get.disk", one_of=["scope:read"])
    def method(ctx: YandexApiContext) -> str:
        return "ok"

    with pytest.raises(TokenConfigError) as exc_info:
        method(context(tmp_path, account="diskacct"))

    assert "Token file not found" in str(exc_info.value)
    assert not (tmp_path / "auth" / "diskacct.token").exists()


def test_dispatch_requires_account_without_managed_tokens(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("YANDEX_DISK_TOKEN", "legacy-env-token")

    @yandex_api_method("disk.resources.get.disk", one_of=["scope:read"])
    def method(ctx: YandexApiContext) -> str:
        return "ok"

    with pytest.raises(TokenConfigError) as exc_info:
        method(context(tmp_path, account=None))

    assert "no token files found" in str(exc_info.value)
    assert not (tmp_path / "auth").exists()


def test_dispatch_infers_account_when_exactly_one_token_file(tmp_path: Path) -> None:
    write_json(
        tmp_path / "auth" / "only.token",
        {
            "email": "user@example.com",
            "token": {"client_id": "client-read"},
        },
    )

    @yandex_api_method("demo.read", one_of=["scope:read"])
    def method(ctx: YandexApiContext) -> str:
        assert ctx.account == "only"
        assert ctx.token_ref.token == "token"
        return "ok"

    assert method(context(tmp_path, account=None)) == "ok"


def test_dispatch_requires_account_when_multiple_token_files(tmp_path: Path) -> None:
    for account in ("one", "two"):
        write_json(
            tmp_path / "auth" / f"{account}.token",
            {
                "email": f"{account}@example.com",
                "token": {"client_id": "client-read"},
            },
        )

    @yandex_api_method("demo.read", one_of=["scope:read"])
    def method(ctx: YandexApiContext) -> str:
        return "ok"

    with pytest.raises(TokenConfigError) as exc_info:
        method(context(tmp_path, account=None))

    assert "multiple token files" in str(exc_info.value)


def test_handle_json_response_only_forbidden_error_rejects_token() -> None:
    with pytest.raises(TokenRejected):
        handle_json_response(FakeResponse(403, {"error": "ForbiddenError"}))

    with pytest.raises(YandexApiError) as exc_info:
        handle_json_response(
            FakeResponse(403, {"error": "OrganizationSettingsAccessForbidden"})
        )

    assert not isinstance(exc_info.value, TokenRejected)
    assert exc_info.value.provider_error == "OrganizationSettingsAccessForbidden"
