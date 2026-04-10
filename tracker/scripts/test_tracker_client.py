#!/usr/bin/env python3
"""Regression tests for Yandex Tracker client helpers."""

from __future__ import annotations

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

import tracker_client

TEST_ORG_ID = "1234567"


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


def test_request_maps_tracker_errors() -> None:
    client = tracker_client.TrackerClient("y0_token", TEST_ORG_ID)
    client.session = FakeSession(FakeResponse(404, text="missing"))

    with pytest.raises(tracker_client.TrackerNotFoundError):
        client._request("GET", "/issues/TEST-1")


def test_search_issues_builds_filter_payload() -> None:
    session = FakeSession(FakeResponse(200, payload=[{"key": "TEST-1"}]))
    client = tracker_client.TrackerClient("y0_token", TEST_ORG_ID)
    client.session = session

    result = client.search_issues(
        filter_obj={"assignee": "me"},
        order="-updatedAt",
        expand=["attachments", "changelog"],
        per_page=10,
        page=2,
    )

    assert result == [{"key": "TEST-1"}]
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url.endswith("/issues/_search")
    assert kwargs["params"] == {"expand": "attachments,changelog", "perPage": 10, "page": 2}
    assert kwargs["json"] == {"filter": {"assignee": "me"}, "order": "-updatedAt"}


def test_load_tracker_client_uses_resolved_token(monkeypatch) -> None:
    monkeypatch.setattr(
        tracker_client,
        "load_runtime_context",
        lambda _path, **_: SimpleNamespace(
            data_dir=Path("/tmp/workspace/yandex-data"),
            config={"urls": {}},
        ),
    )
    monkeypatch.setattr(
        tracker_client,
        "resolve_token",
        lambda **_: SimpleNamespace(
            token="y0_tracker",
            token_data={"org_id": TEST_ORG_ID, "org_type": "360"},
        ),
    )

    client = tracker_client.load_tracker_client("acct")

    assert isinstance(client, tracker_client.TrackerClient)
    assert client.org_id == TEST_ORG_ID
    assert client.session.headers["Authorization"] == "OAuth y0_tracker"
    assert client.session.headers["X-Org-ID"] == TEST_ORG_ID
