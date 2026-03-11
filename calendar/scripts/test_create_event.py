#!/usr/bin/env python3
"""Tests for calendar Telemost event creation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
CAL_LIB = Path(__file__).resolve().parent.parent / 'lib'
for entry in (ROOT_DIR, SCRIPT_DIR, CAL_LIB):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import create_event


class DummyCalendar:
    name = "default"
    url = "https://caldav.example/calendars/demo/default/"


class DummyPrincipal:
    url = "https://caldav.example/users/demo/"


class DummyCalendarClient:
    def __init__(self, *args, **kwargs):
        self.account = "acct"
        self.email = "user@example.com"
        self.token = "calendar-token"
        self.principal = DummyPrincipal()
        self.connected = False

    def connect(self):
        self.connected = True
        return self

    def find_calendar(self):
        return DummyCalendar()


class DummyTelemostClient:
    last_kwargs = None
    last_get_id = None

    def __init__(self, account, data_dir=None):
        self.account = account
        self.data_dir = data_dir

    def create_conference(self, **kwargs):
        DummyTelemostClient.last_kwargs = kwargs
        return {
            "id": "conf-live",
            "join_url": "https://telemost.yandex.ru/j/conf-live",
            "access_level": kwargs["access_level"],
            "waiting_room_level": kwargs["waiting_room_level"],
            "cohosts": kwargs["cohosts"],
        }

    def get_conference(self, conference_id):
        DummyTelemostClient.last_get_id = conference_id
        return {
            "id": conference_id,
            "join_url": f"https://telemost.yandex.ru/j/{conference_id}",
            "access_level": "PUBLIC",
            "waiting_room_level": "PUBLIC",
            "cohosts": [],
        }


class DummyResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def test_create_telemost_event_uses_real_conference(monkeypatch):
    captured = {}

    def fake_put(url, auth=None, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["auth"] = auth
        captured["data"] = data
        captured["headers"] = headers
        captured["timeout"] = timeout
        return DummyResponse(201)

    monkeypatch.setattr(create_event, "YandexCalendarClient", DummyCalendarClient)
    monkeypatch.setattr(create_event, "YandexTelemostClient", DummyTelemostClient)
    monkeypatch.setattr(create_event.requests, "put", fake_put)

    result = create_event.create_telemost_event(
        account="acct",
        summary="Demo",
        start_str="2026-03-12T10:00:00",
        duration_minutes=30,
        attendees=["guest@example.com"],
    )

    assert result["success"] is True
    assert result["telemost_link"] == "https://telemost.yandex.ru/j/conf-live"
    assert result["telemost"]["id"] == "conf-live"
    assert DummyTelemostClient.last_kwargs == {
        "access_level": "PUBLIC",
        "waiting_room_level": "PUBLIC",
        "cohosts": [],
    }
    assert "LOCATION:https://telemost.yandex.ru/j/conf-live" in captured["data"]
    assert "Ссылка: https://telemost.yandex.ru/j/conf-live" in captured["data"]
    assert "METHOD:REQUEST" in captured["data"]
    assert "ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION:mailto:guest@example.com" in captured["data"]
    assert "ORGANIZER;CN=acct:mailto:user@example.com" in captured["data"]


def test_create_telemost_event_passes_overrides(monkeypatch):
    monkeypatch.setattr(create_event, "YandexCalendarClient", DummyCalendarClient)
    monkeypatch.setattr(create_event, "YandexTelemostClient", DummyTelemostClient)
    monkeypatch.setattr(create_event.requests, "put", lambda *args, **kwargs: DummyResponse(204))

    result = create_event.create_telemost_event(
        account="acct",
        summary="Demo",
        start_str="2026-03-12T10:00:00",
        duration_minutes=30,
        attendees=[],
        telemost_access_level="ORGANIZATION",
        telemost_waiting_room="ADMINS",
        telemost_cohosts=["lead@example.com"],
    )

    assert result["success"] is True
    assert result["telemost"]["access_level"] == "ORGANIZATION"
    assert DummyTelemostClient.last_kwargs == {
        "access_level": "ORGANIZATION",
        "waiting_room_level": "ADMINS",
        "cohosts": ["lead@example.com"],
    }


def test_create_telemost_event_without_attendees_uses_publish(monkeypatch):
    captured = {}

    def fake_put(url, auth=None, data=None, headers=None, timeout=None):
        captured["data"] = data
        return DummyResponse(201)

    monkeypatch.setattr(create_event, "YandexCalendarClient", DummyCalendarClient)
    monkeypatch.setattr(create_event, "YandexTelemostClient", DummyTelemostClient)
    monkeypatch.setattr(create_event.requests, "put", fake_put)

    result = create_event.create_telemost_event(
        account="acct",
        summary="Solo",
        start_str="2026-03-12T11:00:00",
        duration_minutes=15,
        attendees=[],
    )

    assert result["success"] is True
    assert "METHOD:PUBLISH" in captured["data"]


def test_create_telemost_event_binds_existing_conference(monkeypatch):
    captured = {}

    def fake_put(url, auth=None, data=None, headers=None, timeout=None):
        captured["data"] = data
        return DummyResponse(201)

    monkeypatch.setattr(create_event, "YandexCalendarClient", DummyCalendarClient)
    monkeypatch.setattr(create_event, "YandexTelemostClient", DummyTelemostClient)
    monkeypatch.setattr(create_event.requests, "put", fake_put)

    result = create_event.create_telemost_event(
        account="acct",
        summary="Bind existing",
        start_str="2026-03-12T12:00:00",
        duration_minutes=15,
        attendees=[],
        telemost_conference_id="existing-42",
    )

    assert result["success"] is True
    assert result["telemost"]["id"] == "existing-42"
    assert result["telemost_link"] == "https://telemost.yandex.ru/j/existing-42"
    assert DummyTelemostClient.last_get_id == "existing-42"
    assert "LOCATION:https://telemost.yandex.ru/j/existing-42" in captured["data"]


def test_create_telemost_event_rejects_conflicting_existing_conference_flags(monkeypatch):
    monkeypatch.setattr(create_event, "YandexCalendarClient", DummyCalendarClient)
    monkeypatch.setattr(create_event, "YandexTelemostClient", DummyTelemostClient)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_event.py",
            "--account",
            "acct",
            "--summary",
            "Conflict",
            "--start",
            "2026-03-12T12:30:00",
            "--duration",
            "15",
            "--telemost-conference-id",
            "existing-42",
            "--telemost-access-level",
            "ORGANIZATION",
            "--json",
        ],
    )
    exit_code = create_event.main()
    assert exit_code == 1


def test_cli_defaults_remain_public(monkeypatch, capsys):
    monkeypatch.setattr(create_event, "YandexCalendarClient", DummyCalendarClient)
    monkeypatch.setattr(create_event, "YandexTelemostClient", DummyTelemostClient)
    monkeypatch.setattr(create_event.requests, "put", lambda *args, **kwargs: DummyResponse(201))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_event.py",
            "--account",
            "acct",
            "--summary",
            "Defaults",
            "--start",
            "2026-03-12T13:00:00",
            "--duration",
            "15",
            "--json",
        ],
    )
    exit_code = create_event.main()
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert out["telemost"]["access_level"] == "PUBLIC"
    assert out["telemost"]["waiting_room_level"] == "PUBLIC"
