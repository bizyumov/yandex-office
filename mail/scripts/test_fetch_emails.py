#!/usr/bin/env python3
"""Regression tests for the Yandex Mail fetcher."""

from __future__ import annotations

import email
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_emails as mail_fetch


class FakeConn:
    def __init__(self, header_message: str):
        self.header_bytes = header_message.encode("utf-8")
        self.calls = []
        self.logged_out = False

    def uid(self, command, uid_bytes, query):
        self.calls.append((command, uid_bytes, query))
        return "OK", [(b"1", self.header_bytes)]

    def logout(self):
        self.logged_out = True


def build_fetcher() -> mail_fetch.EmailFetcher:
    fetcher = mail_fetch.EmailFetcher.__new__(mail_fetch.EmailFetcher)
    fetcher.config = {
        "mail": {
            "filters": {"sender": "keeper@telemost.yandex.ru"},
            "fetch": {"sleep_seconds": 0},
        }
    }
    fetcher.data_dir = Path("/tmp/yandex-data")
    fetcher.state = {"mailboxes": {"alex": {"last_uid": 10}}}
    fetcher.downloaded = []
    fetcher.mailbox_counts = {}
    return fetcher


def test_to_imap_date_normalizes_iso_date() -> None:
    assert mail_fetch.EmailFetcher._to_imap_date("2026-03-12") == "12-Mar-2026"
    assert mail_fetch.EmailFetcher._to_imap_date("12-Mar-2026") == "12-Mar-2026"
    assert mail_fetch.EmailFetcher._to_imap_date("bad-date") is None


def test_fetch_mailbox_dry_run_collects_headers(monkeypatch) -> None:
    header_message = (
        "Subject: =?utf-8?B?0KLQtdGB0YI=?=\r\n"
        "From: news@example.com\r\n"
        "Date: Thu, 12 Mar 2026 10:00:00 +0000\r\n\r\n"
    )
    conn = FakeConn(header_message)
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
    assert fetcher.state["mailboxes"]["alex"]["last_uid"] == 10
    assert fetcher.downloaded == [
        {
            "imap_uid": 11,
            "mailbox": "alex",
            "subject": "Тест",
            "sender": "news@example.com",
            "timestamp": "2026-03-12T10:00:00Z",
            "dry_run": True,
        }
    ]


def test_fetch_all_respects_global_cap() -> None:
    fetcher = build_fetcher()
    fetcher.config["accounts"] = [
        {"name": "one", "email": "user@example.com"},
        {"name": "two", "email": "contact@example.com"},
    ]

    calls = []

    def fake_fetch_mailbox(mailbox_config, max_messages=None, dry_run=False):
        calls.append((mailbox_config["name"], max_messages, dry_run))
        fetcher.downloaded.append({"mailbox": mailbox_config["name"]})
        return 1

    fetcher.fetch_mailbox = fake_fetch_mailbox

    downloaded = fetcher.fetch_all(num_messages=1, dry_run=False)

    assert calls == [("one", 1, False)]
    assert fetcher.mailbox_counts == {"one": 1, "two": 0}
    assert downloaded == [{"mailbox": "one"}]
