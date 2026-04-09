#!/usr/bin/env python3
"""Regression tests for the Yandex Mail fetcher."""

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

import fetch_emails as mail_fetch


class HeaderConn:
    def __init__(self, header_message: str):
        self.header_bytes = header_message.encode("utf-8")
        self.calls = []
        self.logged_out = False

    def uid(self, command, *args):
        self.calls.append((command, args))
        if command == "FETCH":
            return "OK", [(b"1", self.header_bytes)]
        raise AssertionError(f"unexpected uid call: {command}")

    def logout(self):
        self.logged_out = True


class SearchConn:
    def __init__(self, *, uid_result: bytes = b"", search_result: bytes = b"", uid_lookup=None):
        self.uid_result = uid_result
        self.search_result = search_result
        self.uid_lookup = uid_lookup or {}
        self.uid_calls = []
        self.search_calls = []
        self.fetch_calls = []

    def uid(self, command, *args):
        self.uid_calls.append((command, args))
        if command == "SEARCH":
            return "OK", [self.uid_result]
        raise AssertionError(f"unexpected uid command: {command}")

    def search(self, charset, *criteria):
        self.search_calls.append((charset, criteria))
        return "OK", [self.search_result]

    def fetch(self, sequence_id, query):
        self.fetch_calls.append((sequence_id, query))
        uid = self.uid_lookup[sequence_id]
        return "OK", [(f"{sequence_id.decode()} (UID {uid})".encode("ascii"), b"")]


class LogoutConn:
    def __init__(self):
        self.logged_out = False

    def logout(self):
        self.logged_out = True


def build_fetcher(
    *,
    filters: dict | None = None,
    accounts: list[dict[str, str]] | None = None,
    run_options: dict | None = None,
    state: dict | None = None,
) -> mail_fetch.EmailFetcher:
    fetcher = mail_fetch.EmailFetcher.__new__(mail_fetch.EmailFetcher)
    fetcher.config = {
        "mail": {
            "filters": filters or {"sender": "keeper@telemost.yandex.ru"},
            "fetch": {"sleep_seconds": 0},
        },
        "accounts": accounts
        or [
            {"name": "alex", "email": "user@example.com"},
            {"name": "work", "email": "work@example.com"},
        ],
    }
    fetcher.data_dir = Path("/tmp/yandex-data")
    fetcher.state = state or {"filters": {"default": {"mailboxes": {"alex": {"last_uid": 10}}}}}
    fetcher.downloaded = []
    fetcher.mailbox_counts = {}
    fetcher.run_options = {
        "filter": None,
        "sender": None,
        "subject": None,
        "since_date": None,
        "before_date": None,
        "mailbox": None,
        "from_uid": None,
        "no_persist": False,
    }
    if run_options:
        fetcher.run_options.update(run_options)
    fetcher.active_filter = fetcher._resolve_active_filter()
    return fetcher


def test_to_imap_date_normalizes_iso_date() -> None:
    assert mail_fetch.EmailFetcher._to_imap_date("2026-03-12") == "12-Mar-2026"
    assert mail_fetch.EmailFetcher._to_imap_date("12-Mar-2026") == "12-Mar-2026"
    assert mail_fetch.EmailFetcher._to_imap_date("bad-date") is None


def test_legacy_state_normalizes_to_default_filter() -> None:
    fetcher = build_fetcher()
    normalized = fetcher._normalize_state({"mailboxes": {"alex": {"last_uid": 9}}})

    assert normalized == {"filters": {"default": {"mailboxes": {"alex": {"last_uid": 9}}}}}


def test_named_filter_resolution_uses_selected_profile() -> None:
    fetcher = build_fetcher(
        filters={
            "default": "telemost",
            "profiles": {
                "telemost": {"sender": "keeper@telemost.yandex.ru"},
                "forms": {
                    "sender": "forms@yandex.ru",
                    "subject": "New response",
                    "before_date": "2026-03-30",
                },
            },
        },
        run_options={"filter": "forms"},
    )

    assert fetcher.active_filter == {
        "name": "forms",
        "sender": "forms@yandex.ru",
        "subject": "New response",
        "before_date": "2026-03-30",
    }


def test_sender_criteria_handles_email_and_fragment() -> None:
    assert mail_fetch.EmailFetcher._sender_criteria("user@example.com") == [
        'FROM "user"',
        'FROM "example.com"',
    ]
    assert mail_fetch.EmailFetcher._sender_criteria("Smith") == ['FROM "Smith"']


def test_search_emails_uses_ascii_uid_search() -> None:
    fetcher = build_fetcher()
    conn = SearchConn(uid_result=b"8 11 12")

    result = fetcher._search_emails(conn, "user@example.com", 10, subject="Fwd:")

    assert result == [(11, b"11"), (12, b"12")]
    assert conn.uid_calls == [
        (
            "SEARCH",
            (
                None,
                'FROM "user"',
                'FROM "example.com"',
                'SUBJECT "Fwd:"',
            ),
        )
    ]
    assert conn.search_calls == []


def test_search_emails_uses_utf8_search_and_uid_mapping() -> None:
    fetcher = build_fetcher()
    conn = SearchConn(
        search_result=b"1 3",
        uid_lookup={b"1": 41, b"3": 44},
    )

    result = fetcher._search_emails(conn, "Мария", 40)

    assert result == [(41, b"41"), (44, b"44")]
    assert conn.uid_calls == []
    assert conn.search_calls == [("UTF-8", (b'FROM "\xd0\x9c\xd0\xb0\xd1\x80\xd0\xb8\xd1\x8f"',))]
    assert conn.fetch_calls == [(b"1", "(UID)"), (b"3", "(UID)")]


def test_fetch_mailbox_dry_run_collects_headers(monkeypatch) -> None:
    header_message = (
        "Subject: =?utf-8?B?0KLQtdGB0YI=?=\r\n"
        "From: news@example.com\r\n"
        "Date: Thu, 12 Mar 2026 10:00:00 +0000\r\n\r\n"
    )
    conn = HeaderConn(header_message)
    fetcher = build_fetcher()

    monkeypatch.setattr(
        mail_fetch,
        "resolve_token",
        lambda **_: SimpleNamespace(token="y0_mail"),
    )
    fetcher._connect_imap = lambda *_: conn
    fetcher._search_emails = lambda *_args, **_kwargs: [(11, b"11")]

    count = fetcher.fetch_mailbox(
        {"name": "alex", "email": "user@example.com"},
        dry_run=True,
    )

    assert count == 0
    assert conn.logged_out is True
    assert fetcher._get_last_uid("alex", "default") == 10
    assert fetcher.downloaded == [
        {
            "imap_uid": 11,
            "mailbox": "alex",
            "subject": "Тест",
            "sender": "news@example.com",
            "timestamp": "2026-03-12T10:00:00Z",
            "dry_run": True,
            "filter": "default",
        }
    ]


def test_fetch_mailbox_from_uid_is_non_persistent(monkeypatch) -> None:
    fetcher = build_fetcher(run_options={"from_uid": 5000})
    conn = LogoutConn()
    save_calls = []

    monkeypatch.setattr(
        mail_fetch,
        "resolve_token",
        lambda **_: SimpleNamespace(token="y0_mail"),
    )
    fetcher._connect_imap = lambda *_: conn
    fetcher._search_emails = lambda *_args, **_kwargs: [(5001, b"5001")]
    fetcher._process_email = lambda *_args, **_kwargs: {
        "imap_uid": 5001,
        "mailbox": "alex",
        "subject": "Backfill",
        "sender": "user@example.com",
        "timestamp": "2026-03-12T10:00:00Z",
        "attachments": [],
        "dir_name": "2026-03-12_alex_uid5001",
    }
    fetcher._save_state = lambda: save_calls.append("saved")

    fetched = fetcher.fetch_mailbox({"name": "alex", "email": "user@example.com"})

    assert fetched == 1
    assert fetcher._get_last_uid("alex", "default") == 10
    assert save_calls == []
    assert conn.logged_out is True


def test_fetch_all_respects_global_cap() -> None:
    fetcher = build_fetcher()

    calls = []

    def fake_fetch_mailbox(mailbox_config, max_messages=None, dry_run=False):
        calls.append((mailbox_config["name"], max_messages, dry_run))
        fetcher.downloaded.append({"mailbox": mailbox_config["name"]})
        return 1

    fetcher.fetch_mailbox = fake_fetch_mailbox

    downloaded = fetcher.fetch_all(num_messages=1, dry_run=False)

    assert calls == [("alex", 1, False)]
    assert fetcher.mailbox_counts == {"alex": 1, "work": 0}
    assert downloaded == [{"mailbox": "alex"}]


def test_fetch_all_restricts_mailbox_selection() -> None:
    fetcher = build_fetcher(run_options={"mailbox": "work"})
    calls = []
    fetcher.fetch_mailbox = lambda mailbox_config, **kwargs: calls.append(mailbox_config["name"]) or 0

    fetcher.fetch_all()

    assert calls == ["work"]


def test_fetch_all_rejects_unknown_mailbox() -> None:
    fetcher = build_fetcher(run_options={"mailbox": "missing"})

    with pytest.raises(ValueError, match='Unknown mailbox "missing"'):
        fetcher.fetch_all()
