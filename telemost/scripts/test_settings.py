#!/usr/bin/env python3
"""Tests for Telemost organization settings client and CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common.auth import ResolvedToken
from telemost.lib import client as telemost_client
import settings as settings_cli

TEST_ORG_ID = 1234567


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
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, json=None, params=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "json": json, "params": params})
        if not self.responses:
            raise AssertionError("Unexpected request with no queued response")
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def stub_token(monkeypatch):
    monkeypatch.setattr(
        telemost_client,
        "resolve_token",
        lambda **_: ResolvedToken(
            account="acct",
            skill="telemost",
            token="secret",
            token_key="token.telemost",
            source_key="token.telemost",
            token_path=Path("/tmp/acct.token"),
            token_data={"token.telemost": "secret", "org_id": str(TEST_ORG_ID)},
            email="user@example.com",
        ),
    )


def test_get_org_settings_uses_token_org_id():
    session = FakeSession([
        FakeResponse(200, {"waiting_room_level_adhoc": {"value": "PUBLIC"}}),
    ])
    client = telemost_client.YandexTelemostClient("acct", session=session)
    result = client.get_org_settings()
    assert result["org_id"] == TEST_ORG_ID
    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"].endswith(f"/organizations/{TEST_ORG_ID}/settings")


def test_update_org_settings_normalizes_payload():
    session = FakeSession([
        FakeResponse(
            200,
            {
                "waiting_room_level_adhoc": {"value": "PUBLIC"},
                "cloud_recording_allowed_roles": {"value": ["OWNER"]},
            },
        )
    ])
    client = telemost_client.YandexTelemostClient("acct", session=session)
    payload = client.build_org_settings_payload(
        waiting_room_level_adhoc="public",
        cloud_recording_allowed_roles=["owner"],
    )
    result = client.update_org_settings(payload)
    assert result["org_id"] == TEST_ORG_ID
    assert session.calls[0]["method"] == "PUT"
    assert session.calls[0]["json"] == {
        "waiting_room_level_adhoc": {"value": "PUBLIC"},
        "cloud_recording_allowed_roles": {"value": ["OWNER"]},
    }


def test_update_org_settings_preserves_unknown_fields_from_file_payload():
    session = FakeSession([
        FakeResponse(
            200,
            {
                "is_incoming_phone_calls_turned_on": True,
                "waiting_room_level_calendar": {"value": "PUBLIC"},
            },
        )
    ])
    client = telemost_client.YandexTelemostClient("acct", session=session)
    payload = client.build_org_settings_payload(
        file_payload={
            "is_incoming_phone_calls_turned_on": True,
            "waiting_room_level_calendar": {"value": "PUBLIC"},
        }
    )
    client.update_org_settings(payload)
    assert session.calls[0]["json"] == {
        "is_incoming_phone_calls_turned_on": True,
        "waiting_room_level_calendar": {"value": "PUBLIC"},
    }


def test_invalid_org_role_rejected():
    client = telemost_client.YandexTelemostClient("acct", session=FakeSession([]))
    with pytest.raises(ValueError):
        client.build_org_settings_payload(cloud_recording_allowed_roles=["ADMIN"])


def test_settings_cli_get(monkeypatch, capsys):
    class StubClient:
        def __init__(self, account):
            self.account = account

        def get_org_settings(self, *, org_id=None):
            return {"org_id": org_id or TEST_ORG_ID, "waiting_room_level_adhoc": {"value": "PUBLIC"}}

    monkeypatch.setattr(settings_cli, "YandexTelemostClient", StubClient)
    monkeypatch.setattr(sys, "argv", ["settings.py", "get", "--account", "acct"])
    code = settings_cli.main()
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["org_id"] == TEST_ORG_ID


def test_settings_cli_update_from_flags(monkeypatch, capsys):
    captured = {}

    class StubClient:
        def __init__(self, account):
            self.account = account

        def build_org_settings_payload(self, **kwargs):
            captured["build"] = kwargs
            return {"waiting_room_level_calendar": {"value": "ADMINS"}}

        def update_org_settings(self, payload, *, org_id=None):
            captured["payload"] = payload
            captured["org_id"] = org_id
            return {"org_id": org_id or TEST_ORG_ID, **payload}

    monkeypatch.setattr(settings_cli, "YandexTelemostClient", StubClient)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "settings.py",
            "update",
            "--account",
            "acct",
            "--waiting-room-calendar",
            "ADMINS",
        ],
    )
    code = settings_cli.main()
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert captured["payload"] == {"waiting_room_level_calendar": {"value": "ADMINS"}}
    assert out["waiting_room_level_calendar"]["value"] == "ADMINS"
