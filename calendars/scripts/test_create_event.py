#!/usr/bin/env python3
"""Tests for calendar Telemost event creation."""

from __future__ import annotations

from datetime import datetime
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from calendars.lib import client as calendar_client_module
import create_event


class DummyCalendar:
    name = "default"
    url = "https://caldav.example/calendars/demo/default/"


class DummyPrincipal:
    url = "https://caldav.example/users/demo/"


class DummyCalendarClient:
    put_handler = None

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

    def put_event(self, *, event_url, ical_data):
        if DummyCalendarClient.put_handler is not None:
            return DummyCalendarClient.put_handler(
                event_url,
                auth=(self.email, self.token),
                data=ical_data,
                headers={"Content-Type": "text/calendar; charset=utf-8"},
                timeout=30,
            )
        return DummyResponse(201)


class DummyTelemostClient:
    calls = []
    init_count = 0
    last_kwargs = None
    last_get_id = None
    last_update_id = None
    last_update_kwargs = None

    def __init__(self, account, data_dir=None):
        DummyTelemostClient.init_count += 1
        self.account = account
        self.data_dir = data_dir

    def create_conference(self, **kwargs):
        DummyTelemostClient.calls.append(("create", kwargs))
        DummyTelemostClient.last_kwargs = kwargs
        return {
            "id": "conf-live",
            "join_url": "https://telemost.yandex.ru/j/conf-live",
            "access_level": kwargs["access_level"],
            "waiting_room_level": kwargs["waiting_room_level"],
            "cohosts": kwargs["cohosts"],
        }

    def get_conference(self, conference_id):
        DummyTelemostClient.calls.append(("get", conference_id))
        DummyTelemostClient.last_get_id = conference_id
        return {
            "id": conference_id,
            "join_url": f"https://telemost.yandex.ru/j/{conference_id}",
            "access_level": "PUBLIC",
            "waiting_room_level": "PUBLIC",
            "cohosts": [],
        }

    def update_conference(self, conference_id, **kwargs):
        DummyTelemostClient.calls.append(("update", conference_id, kwargs))
        DummyTelemostClient.last_update_id = conference_id
        DummyTelemostClient.last_update_kwargs = kwargs
        return {
            "id": conference_id,
            "join_url": f"https://telemost.yandex.ru/j/{conference_id}",
            "access_level": kwargs.get("access_level"),
            "waiting_room_level": kwargs.get("waiting_room_level"),
            "cohosts": kwargs.get("cohosts"),
        }


class DummyResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def write_calendar_token(data_dir: Path) -> Path:
    auth_dir = data_dir / "auth"
    auth_dir.mkdir(parents=True)
    token_path = auth_dir / "acct.token"
    token_path.write_text(
        json.dumps(
            {
                "email": "user@example.com",
                "calendar-token": {
                    "client_id": "902e7ef779014d31b94d69d8cc863034",
                },
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "config.agent.json").write_text("{}\n", encoding="utf-8")
    return token_path


def test_create_telemost_event_uses_real_conference(monkeypatch):
    captured = {}
    DummyTelemostClient.calls = []
    DummyTelemostClient.init_count = 0

    def fake_put(url, auth=None, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["auth"] = auth
        captured["data"] = data
        captured["headers"] = headers
        captured["timeout"] = timeout
        return DummyResponse(201)

    DummyCalendarClient.put_handler = fake_put
    monkeypatch.setattr(create_event, "YandexCalendarClient", DummyCalendarClient)
    monkeypatch.setattr(create_event, "YandexTelemostClient", DummyTelemostClient)

    result = create_event.create_telemost_event(
        account="acct",
        summary="Demo",
        start_str="2026-03-12T10:00:00",
        duration_minutes=30,
        attendees=["user@example.com"],
        timezone_name="Europe/Moscow",
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
    assert "DTSTART;TZID=Europe/Moscow:20260312T100000" in captured["data"]
    assert "ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION:mailto:user@example.com" in captured["data"]
    assert "ORGANIZER;CN=acct:mailto:user@example.com" in captured["data"]


def test_create_telemost_event_passes_overrides(monkeypatch):
    DummyTelemostClient.calls = []
    DummyCalendarClient.put_handler = lambda *args, **kwargs: DummyResponse(204)
    monkeypatch.setattr(create_event, "YandexCalendarClient", DummyCalendarClient)
    monkeypatch.setattr(create_event, "YandexTelemostClient", DummyTelemostClient)

    result = create_event.create_telemost_event(
        account="acct",
        summary="Demo",
        start_str="2026-03-12T10:00:00",
        duration_minutes=30,
        attendees=[],
        timezone_name="Europe/Moscow",
        telemost_access_level="ORGANIZATION",
        telemost_waiting_room="ADMINS",
        telemost_cohosts=["contact@example.com"],
    )

    assert result["success"] is True
    assert result["telemost"]["access_level"] == "ORGANIZATION"
    assert DummyTelemostClient.last_kwargs == {
        "access_level": "ORGANIZATION",
        "waiting_room_level": "ADMINS",
        "cohosts": ["contact@example.com"],
    }


def test_create_telemost_event_without_attendees_uses_publish(monkeypatch):
    captured = {}
    DummyTelemostClient.calls = []

    def fake_put(url, auth=None, data=None, headers=None, timeout=None):
        captured["data"] = data
        return DummyResponse(201)

    DummyCalendarClient.put_handler = fake_put
    monkeypatch.setattr(create_event, "YandexCalendarClient", DummyCalendarClient)
    monkeypatch.setattr(create_event, "YandexTelemostClient", DummyTelemostClient)

    result = create_event.create_telemost_event(
        account="acct",
        summary="Solo",
        start_str="2026-03-12T11:00:00",
        duration_minutes=15,
        attendees=[],
        timezone_name="Europe/Moscow",
    )

    assert result["success"] is True
    assert "METHOD:PUBLISH" in captured["data"]


def test_create_telemost_event_binds_existing_conference(monkeypatch):
    captured = {}
    DummyTelemostClient.calls = []

    def fake_put(url, auth=None, data=None, headers=None, timeout=None):
        captured["data"] = data
        return DummyResponse(201)

    DummyCalendarClient.put_handler = fake_put
    monkeypatch.setattr(create_event, "YandexCalendarClient", DummyCalendarClient)
    monkeypatch.setattr(create_event, "YandexTelemostClient", DummyTelemostClient)

    result = create_event.create_telemost_event(
        account="acct",
        summary="Bind existing",
        start_str="2026-03-12T12:00:00",
        duration_minutes=15,
        attendees=[],
        timezone_name="Europe/Moscow",
        telemost_conference_id="existing-42",
    )

    assert result["success"] is True
    assert result["telemost"]["id"] == "existing-42"
    assert result["telemost_link"] == "https://telemost.yandex.ru/j/existing-42"
    assert DummyTelemostClient.last_get_id == "existing-42"
    assert "LOCATION:https://telemost.yandex.ru/j/existing-42" in captured["data"]


def test_create_telemost_event_updates_existing_conference_settings(monkeypatch):
    captured = {}
    DummyTelemostClient.calls = []

    def fake_put(url, auth=None, data=None, headers=None, timeout=None):
        captured["data"] = data
        return DummyResponse(201)

    DummyCalendarClient.put_handler = fake_put
    monkeypatch.setattr(create_event, "YandexCalendarClient", DummyCalendarClient)
    monkeypatch.setattr(create_event, "YandexTelemostClient", DummyTelemostClient)

    result = create_event.create_telemost_event(
        account="acct",
        summary="Update existing",
        start_str="2026-03-12T12:00:00",
        duration_minutes=15,
        attendees=[],
        timezone_name="Europe/Moscow",
        telemost_conference_id="existing-42",
        telemost_access_level="ORGANIZATION",
        telemost_waiting_room="ADMINS",
        telemost_cohosts=["contact@example.com"],
        telemost_settings_supplied=True,
        telemost_cohosts_supplied=True,
    )

    assert result["success"] is True
    assert DummyTelemostClient.calls[0] == (
        "update",
        "existing-42",
        {
            "access_level": "ORGANIZATION",
            "waiting_room_level": "ADMINS",
            "cohosts": ["contact@example.com"],
        },
    )
    assert DummyTelemostClient.calls[1] == ("get", "existing-42")
    assert "LOCATION:https://telemost.yandex.ru/j/existing-42" in captured["data"]


def test_create_telemost_event_reuses_link_and_uid_without_telemost_call(monkeypatch):
    captured = {}
    DummyTelemostClient.calls = []
    DummyTelemostClient.init_count = 0

    def fake_put(url, auth=None, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        return DummyResponse(201)

    DummyCalendarClient.put_handler = fake_put
    monkeypatch.setattr(create_event, "YandexCalendarClient", DummyCalendarClient)
    monkeypatch.setattr(create_event, "YandexTelemostClient", DummyTelemostClient)

    result = create_event.create_telemost_event(
        account="acct",
        summary="Reuse",
        start_str="2026-03-12T12:00:00",
        duration_minutes=15,
        attendees=[],
        timezone_name="Europe/Moscow",
        event_uid="event-42",
        telemost_link="https://telemost.yandex.ru/j/reused",
    )

    assert result["uid"] == "event-42"
    assert "event-42.ics" in captured["url"]
    assert result["telemost_link"] == "https://telemost.yandex.ru/j/reused"
    assert DummyTelemostClient.init_count == 0


def test_create_telemost_event_rejects_link_settings_without_conference_id(monkeypatch):
    DummyCalendarClient.put_handler = None
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
            "--timezone",
            "Europe/Moscow",
            "--duration",
            "15",
            "--telemost-link",
            "https://telemost.yandex.ru/j/reused",
            "--telemost-access-level",
            "ORGANIZATION",
            "--json",
        ],
    )
    exit_code = create_event.main()
    assert exit_code == 1


def test_create_telemost_event_requires_explicit_time_context(monkeypatch):
    DummyCalendarClient.put_handler = lambda *args, **kwargs: DummyResponse(201)
    monkeypatch.setattr(create_event, "YandexCalendarClient", DummyCalendarClient)
    monkeypatch.setattr(create_event, "YandexTelemostClient", DummyTelemostClient)

    with pytest.raises(ValueError, match="exactly one"):
        create_event.create_telemost_event(
            account="acct",
            summary="No timezone",
            start_str="2026-03-12T13:00:00",
            duration_minutes=15,
            attendees=[],
        )

    with pytest.raises(ValueError, match="exactly one"):
        create_event.create_telemost_event(
            account="acct",
            summary="Both",
            start_str="2026-03-12T13:00:00",
            duration_minutes=15,
            attendees=[],
            timezone_name="Europe/Moscow",
            utc_offset="+03:00",
        )


def test_create_telemost_event_aware_start_converts_to_utc_offset(monkeypatch):
    captured = {}
    DummyCalendarClient.put_handler = lambda url, auth=None, data=None, headers=None, timeout=None: captured.setdefault("data", data) or DummyResponse(201)
    monkeypatch.setattr(create_event, "YandexCalendarClient", DummyCalendarClient)
    monkeypatch.setattr(create_event, "YandexTelemostClient", DummyTelemostClient)

    result = create_event.create_telemost_event(
        account="acct",
        summary="Offset",
        start_str="2026-03-12T10:00:00+00:00",
        duration_minutes=15,
        attendees=[],
        utc_offset="+03:00",
    )

    assert result["start"] == "2026-03-12T13:00:00+03:00"
    assert result["utc_offset"] == "+03:00"
    assert "DTSTART:20260312T100000Z" in captured["data"]


def test_cli_defaults_remain_public(monkeypatch, capsys):
    DummyTelemostClient.calls = []
    DummyCalendarClient.put_handler = lambda *args, **kwargs: DummyResponse(201)
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
            "Defaults",
            "--start",
            "2026-03-12T13:00:00",
            "--timezone",
            "Europe/Moscow",
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


def test_create_event_marks_calendar_token_good_through_standard_dispatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    # Business success is not enough for GH41: every token-backed method must
    # pass through dispatch, which proves itself by writing good_at.
    data_dir = tmp_path / "yandex-data"
    token_path = write_calendar_token(data_dir)

    captured = {}

    class FakeDAVClient:
        def __init__(self, *, url, username, password):
            captured["dav_auth"] = (username, password)

        def principal(self):
            return type(
                "Principal",
                (),
                {"calendars": lambda self: [DummyCalendar()]},
            )()

    def fake_put(url, auth=None, data=None, headers=None, timeout=None):
        captured["put_auth"] = auth
        captured["data"] = data
        return DummyResponse(201)

    monkeypatch.setattr(calendar_client_module.caldav, "DAVClient", FakeDAVClient)
    monkeypatch.setattr(calendar_client_module.requests, "put", fake_put)
    monkeypatch.setattr(create_event, "YandexTelemostClient", DummyTelemostClient)

    result = create_event.create_telemost_event(
        account="acct",
        summary="Dispatch route",
        start_str="2026-03-12T14:00:00",
        duration_minutes=30,
        attendees=[],
        data_dir=str(data_dir),
        timezone_name="Europe/Moscow",
    )

    saved = json.loads(token_path.read_text(encoding="utf-8"))
    assert result["success"] is True
    assert captured["dav_auth"] == ("user@example.com", "calendar-token")
    assert captured["put_auth"] == ("user@example.com", "calendar-token")
    assert "good_at" in saved["calendar-token"]


def test_list_events_uses_supported_calendar_search(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "yandex-data"
    write_calendar_token(data_dir)
    captured = {}

    class FakeEvent:
        data = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:event-1
DTSTART:20260312T140000Z
DTEND:20260312T143000Z
SUMMARY:Search result
END:VEVENT
END:VCALENDAR
"""

    class FakeCalendar:
        name = "default"

        def search(self, **kwargs):
            captured["search"] = kwargs
            return [FakeEvent()]

    class FakeDAVClient:
        def __init__(self, *, url, username, password):
            captured["dav_auth"] = (username, password)

        def principal(self):
            return type(
                "Principal",
                (),
                {"calendars": lambda self: [FakeCalendar()]},
            )()

    monkeypatch.setattr(calendar_client_module.caldav, "DAVClient", FakeDAVClient)

    client = calendar_client_module.YandexCalendarClient(
        "acct",
        data_dir=str(data_dir),
    )
    start = datetime(2026, 3, 12, 14, 0)
    end = datetime(2026, 3, 12, 15, 0)

    events = client.list_events(start=start, end=end)

    assert captured["dav_auth"] == ("user@example.com", "calendar-token")
    assert captured["search"] == {
        "start": start,
        "end": end,
        "event": True,
        "expand": True,
        "split_expanded": False,
    }
    assert events[0]["uid"] == "event-1"
