#!/usr/bin/env python3
"""Tests for Telemost conference client and CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common.auth import ResolvedToken
from telemost.lib import client as telemost_client
import conference as conference_cli


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
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "json": json,
                "params": params,
                "timeout": timeout,
            }
        )
        if not self.responses:
            raise AssertionError("Unexpected request with no queued response")
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def stub_token(monkeypatch):
    monkeypatch.setattr(
        telemost_client,
        "load_runtime_context",
        lambda _path, **_: SimpleNamespace(
            data_dir=Path("/tmp/workspace/yandex-data"),
            config={"urls": {}},
        ),
    )
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
            token_data={"token.telemost": "secret"},
            email="user@example.com",
        ),
    )


def test_create_conference_defaults():
    session = FakeSession(
        [
            FakeResponse(201, {"id": "conf-1", "join_url": "https://telemost.yandex.ru/j/1"}),
            FakeResponse(
                200,
                {
                    "id": "conf-1",
                    "join_url": "https://telemost.yandex.ru/j/1",
                    "access_level": "PUBLIC",
                    "waiting_room_level": "PUBLIC",
                },
            ),
            FakeResponse(200, {"cohosts": []}),
        ]
    )
    client = telemost_client.YandexTelemostClient("acct", session=session)
    result = client.create_conference()

    assert result["id"] == "conf-1"
    assert result["join_url"] == "https://telemost.yandex.ru/j/1"
    assert result["access_level"] == "PUBLIC"
    assert result["waiting_room_level"] == "PUBLIC"
    assert result["cohosts"] == []
    assert session.calls[0]["json"] == {
        "access_level": "PUBLIC",
        "waiting_room_level": "PUBLIC",
        "cohosts": [],
    }


def test_create_conference_with_overrides():
    session = FakeSession(
        [
            FakeResponse(201, {"id": "conf-2", "join_url": "https://telemost.yandex.ru/j/2"}),
            FakeResponse(
                200,
                {
                    "id": "conf-2",
                    "join_url": "https://telemost.yandex.ru/j/2",
                    "access_level": "ORGANIZATION",
                    "waiting_room_level": "ADMINS",
                    "live_stream": {
                        "watch_url": "https://telemost.yandex.ru/watch/2",
                    },
                },
            ),
            FakeResponse(200, {"cohosts": [{"email": "contact@example.com"}]}),
        ]
    )
    client = telemost_client.YandexTelemostClient("acct", session=session)
    result = client.create_conference(
        access_level="ORGANIZATION",
        waiting_room_level="ADMINS",
        cohosts=["contact@example.com"],
        live_stream={"access_level": "PUBLIC", "title": "Broadcast"},
    )

    assert result["live_stream"]["watch_url"] == "https://telemost.yandex.ru/watch/2"
    assert result["cohosts"] == ["contact@example.com"]
    assert session.calls[0]["json"] == {
        "access_level": "ORGANIZATION",
        "waiting_room_level": "ADMINS",
        "live_stream": {"access_level": "PUBLIC", "title": "Broadcast"},
        "cohosts": [{"email": "contact@example.com"}],
    }


def test_update_conference_with_patch_and_cohosts():
    session = FakeSession(
        [
            FakeResponse(200, {"id": "conf-3", "join_url": "https://telemost.yandex.ru/j/3"}),
            FakeResponse(204, None),
            FakeResponse(
                200,
                {
                    "id": "conf-3",
                    "join_url": "https://telemost.yandex.ru/j/3",
                    "access_level": "PUBLIC",
                    "waiting_room_level": "ORGANIZATION",
                },
            ),
            FakeResponse(200, {"cohosts": [{"email": "contact@example.com"}]}),
        ]
    )
    client = telemost_client.YandexTelemostClient("acct", session=session)
    result = client.update_conference(
        "conf-3",
        waiting_room_level="ORGANIZATION",
        cohosts=["contact@example.com"],
    )

    assert result["waiting_room_level"] == "ORGANIZATION"
    assert result["cohosts"] == ["contact@example.com"]
    assert session.calls[0]["method"] == "PATCH"
    assert session.calls[0]["json"] == {"waiting_room_level": "ORGANIZATION"}
    assert session.calls[1]["method"] == "PUT"
    assert session.calls[1]["json"] == {"cohosts": [{"email": "contact@example.com"}]}


def test_get_conference_maps_404():
    session = FakeSession([FakeResponse(404, {"message": "not found"})])
    client = telemost_client.YandexTelemostClient("acct", session=session)
    with pytest.raises(telemost_client.TelemostError) as exc:
        client.get_conference("missing")
    assert exc.value.to_dict()["status_code"] == 404


def test_create_conference_maps_402():
    session = FakeSession([FakeResponse(402, {"message": "payment required"})])
    client = telemost_client.YandexTelemostClient("acct", session=session)
    with pytest.raises(telemost_client.TelemostError) as exc:
        client.create_conference(live_stream={"title": "Paid"})
    assert "paid" in str(exc.value).lower()


def test_invalid_enum_and_email_validation():
    client = telemost_client.YandexTelemostClient("acct", session=FakeSession([]))
    with pytest.raises(ValueError):
        client.create_conference(access_level="private")
    with pytest.raises(ValueError):
        client.create_conference(cohosts=["not-an-email"])


def test_cli_create_defaults(monkeypatch, capsys):
    captured = {}

    class StubClient:
        def __init__(self, account):
            captured["account"] = account

        def create_conference(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"id": "conf-4", "join_url": "https://telemost.yandex.ru/j/4"}

    monkeypatch.setattr(conference_cli, "YandexTelemostClient", StubClient)
    monkeypatch.setattr(sys, "argv", ["conference.py", "create", "--account", "acct"])

    exit_code = conference_cli.main()
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert captured["kwargs"] == {
        "access_level": "PUBLIC",
        "waiting_room_level": "PUBLIC",
        "cohosts": [],
        "live_stream": None,
    }
    assert out["id"] == "conf-4"


def test_cli_update_with_clear_cohosts(monkeypatch, capsys):
    captured = {}

    class StubClient:
        def __init__(self, account):
            captured["account"] = account

        def update_conference(self, conference_id, **kwargs):
            captured["conference_id"] = conference_id
            captured["kwargs"] = kwargs
            return {"id": conference_id, "join_url": "https://telemost.yandex.ru/j/5"}

    monkeypatch.setattr(conference_cli, "YandexTelemostClient", StubClient)
    monkeypatch.setattr(
        sys,
        "argv",
        ["conference.py", "update", "--account", "acct", "--id", "conf-5", "--cohosts", ""],
    )

    exit_code = conference_cli.main()
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert captured["conference_id"] == "conf-5"
    assert captured["kwargs"]["cohosts"] == []
    assert out["id"] == "conf-5"
