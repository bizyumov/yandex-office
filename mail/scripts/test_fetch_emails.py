#!/usr/bin/env python3
"""Regression tests for the Yandex Mail fetcher."""

from __future__ import annotations

import json
import os
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mail.scripts import fetch_emails as mail_fetch


def test_message_bodies_include_inline_text_parts():
    msg = EmailMessage()
    msg.set_content("plain receipt body", disposition="inline")
    msg.add_alternative("<p>html receipt body</p>", subtype="html", disposition="inline")

    text_body, html_body = mail_fetch.EmailFetcher._message_bodies(msg)

    assert text_body == "plain receipt body\n"
    assert html_body == "<p>html receipt body</p>\n"


def test_message_bodies_skip_attachments():
    msg = EmailMessage()
    msg.set_content("receipt body")
    msg.add_attachment("not body", filename="note.txt")

    text_body, html_body = mail_fetch.EmailFetcher._message_bodies(msg)

    assert text_body == "receipt body\n"
    assert html_body is None


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
    def __init__(
        self,
        *,
        uid_result: bytes = b"",
        search_result: bytes = b"",
        uid_lookup=None,
        bytes_only_uid_fetch: bool = False,
    ):
        self.uid_result = uid_result
        self.search_result = search_result
        self.uid_lookup = uid_lookup or {}
        self.bytes_only_uid_fetch = bytes_only_uid_fetch
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
        if self.bytes_only_uid_fetch:
            return "OK", [f"{sequence_id.decode()} (UID {uid})".encode("ascii")]
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
            {"name": "beta", "email": "beta@example.test"},
        ],
    }
    fetcher.data_dir = Path("/tmp/yandex-data")
    fetcher.state = state or {"filters": {"telemost": {"accounts": {"alex": {"last_uid": 10}}}}}
    fetcher.downloaded = []
    fetcher.account_counts = {}
    fetcher.filter_counts = {}
    fetcher.run_options = {
        "filter": None,
        "sender": None,
        "subject": None,
        "since_date": None,
        "before_date": None,
        "account": None,
        "from_uid": None,
        "uid": None,
        "no_persist": False,
        "preview_body": False,
    }
    if run_options:
        fetcher.run_options.update(run_options)
    fetcher.named_filters = fetcher._resolve_named_filters()
    fetcher.run_filters = fetcher._resolve_run_filters()
    fetcher.active_filter = fetcher.run_filters[0] if len(fetcher.run_filters) == 1 else None
    return fetcher


def test_to_imap_date_normalizes_iso_date() -> None:
    assert mail_fetch.EmailFetcher._to_imap_date("2026-03-12") == "12-Mar-2026"
    assert mail_fetch.EmailFetcher._to_imap_date("12-Mar-2026") == "12-Mar-2026"
    assert mail_fetch.EmailFetcher._to_imap_date("bad-date") is None


def test_default_state_normalizes_to_telemost_filter() -> None:
    fetcher = build_fetcher()
    normalized = fetcher._normalize_state({"filters": {"default": {"accounts": {"alex": {"last_uid": 9}}}}})

    assert normalized == {"filters": {"telemost": {"accounts": {"alex": {"last_uid": 9}}}}}


def test_named_filter_resolution_uses_selected_filter() -> None:
    fetcher = build_fetcher(
        filters={
            "telemost": {"sender": "keeper@telemost.yandex.ru"},
            "forms": {
                "sender": "forms@yandex.ru",
                "subject": "New response",
                "before_date": "2026-03-30",
            },
        },
        run_options={"filter": "forms"},
    )

    assert fetcher.run_filters == [{
        "name": "forms",
        "enabled": True,
        "sender": "forms@yandex.ru",
        "subject": "New response",
        "before_date": "2026-03-30",
    }]


def test_named_filter_resolution_supports_any_branches() -> None:
    fetcher = build_fetcher(
        filters={
            "payment_receipts": {
                "enabled": True,
                "any": [
                    {"sender": "receipts-a.example"},
                    {"sender": "receipts-b.example", "since_date": "2026-05-01"},
                ],
            },
        },
        run_options={"filter": "payment_receipts"},
    )

    assert fetcher.run_filters == [{
        "name": "payment_receipts",
        "enabled": True,
        "any": [
            {
                "sender": "receipts-a.example",
                "branch_key": "sha256:1f41d48b64ec678df112ba10117dbc901d7b6d6f12cdb9af992f6bf829ffba2d",
            },
            {
                "sender": "receipts-b.example",
                "since_date": "2026-05-01",
                "branch_key": "sha256:d93bde2826287e3d1af6fa08a818d35a04ecc41f18da0bb7f0339e683660b26d",
            },
        ],
    }]


def test_fetch_account_any_filter_uses_filter_local_branch_state(tmp_path) -> None:
    fetcher = build_fetcher(
        filters={
            "payment_receipts": {
                "any": [
                    {"sender": "receipts-a.example"},
                    {"sender": "receipts-b.example"},
                ],
            },
        },
        run_options={"filter": "payment_receipts"},
        state={"filters": {"payment_receipts": {"accounts": {"alex": {"last_uid": 999}}}}},
    )
    fetcher.data_dir = tmp_path
    conn = LogoutConn()
    calls = []
    processed = []

    fetcher._connect_imap = lambda *_: conn

    def fake_search_by_criteria(_conn, criteria, last_uid, *, max_uid=None):
        calls.append((criteria, last_uid, max_uid))
        return [(101, b"101"), (202, b"202")]

    fetcher._search_emails_by_criteria = fake_search_by_criteria

    def fake_process(_conn, uid_bytes, uid, account, filter_, **_kw):
        processed.append((uid, account, filter_))
        sender = "<noreply@receipts-a.example>" if uid == 101 else "<check@receipts-b.example>"
        return {
            "imap_uid": uid,
            "account": account,
            "filter": filter_,
            "subject": "Receipt",
            "sender": sender,
            "timestamp": "2026-05-23T10:00:00Z",
            "attachments": [],
        }

    fetcher._process_email = fake_process

    fetched = fetcher.fetch_account({"name": "alex", "email": "user@example.com"}, fetcher.run_filters[0])

    assert fetched == 2
    assert calls == [(['OR', 'FROM "receipts-a.example"', 'FROM "receipts-b.example"'], 0, None)]
    assert processed == [(101, "alex", "payment_receipts"), (202, "alex", "payment_receipts")]
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    account_state = state["filters"]["payment_receipts"]["accounts"]["alex"]
    assert account_state["last_uid"] == 202
    assert account_state["last_received_date"] == "2026-05-23"
    assert isinstance(account_state["last_check"], str)
    assert account_state["sha256:1f41d48b64ec678df112ba10117dbc901d7b6d6f12cdb9af992f6bf829ffba2d"] == 101
    assert account_state["sha256:c296cfc07baf6e2886e4ee48654cd252ac59fb92f2bbdebbb3609f6a469cbaa8"] == 202


def test_fetch_account_any_filter_backfills_missing_branch_to_high_water(tmp_path) -> None:
    first_key = "sha256:1f41d48b64ec678df112ba10117dbc901d7b6d6f12cdb9af992f6bf829ffba2d"
    second_key = "sha256:c296cfc07baf6e2886e4ee48654cd252ac59fb92f2bbdebbb3609f6a469cbaa8"
    (tmp_path / "state.json").write_text(
        json.dumps(
            {
                "filters": {
                    "payment_receipts": {
                        "accounts": {
                            "alex": {first_key: 1000},
                        },
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    fetcher = build_fetcher(
        filters={
            "payment_receipts": {
                "any": [
                    {"sender": "receipts-a.example"},
                    {"sender": "receipts-b.example"},
                ],
            },
        },
        run_options={"filter": "payment_receipts"},
    )
    fetcher.data_dir = tmp_path
    fetcher.state = fetcher._load_state()
    conn = LogoutConn()
    calls = []
    fetcher._connect_imap = lambda *_: conn

    def fake_search_by_criteria(_conn, criteria, last_uid, *, max_uid=None):
        calls.append((criteria, last_uid, max_uid))
        if max_uid == 1000:
            return []
        return [(1001, b"1001")]

    fetcher._search_emails_by_criteria = fake_search_by_criteria
    fetcher._process_email = lambda _conn, uid_bytes, uid, account, filter_, **_kw: {
        "imap_uid": uid,
        "account": account,
        "filter": filter_,
        "subject": "Receipt",
        "sender": "<check@receipts-b.example>",
        "timestamp": "2026-05-23T10:00:00Z",
        "attachments": [],
    }

    fetched = fetcher.fetch_account({"name": "alex", "email": "user@example.com"}, fetcher.run_filters[0])

    assert fetched == 1
    assert calls == [
        (['FROM "receipts-b.example"'], 0, 1000),
        (['OR', 'FROM "receipts-a.example"', 'FROM "receipts-b.example"'], 1000, None),
    ]
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    account_state = state["filters"]["payment_receipts"]["accounts"]["alex"]
    assert account_state["last_uid"] == 1001
    assert account_state["last_received_date"] == "2026-05-23"
    assert isinstance(account_state["last_check"], str)
    assert account_state[first_key] == 1000
    assert account_state[second_key] == 1001


def test_fetch_account_any_filter_advances_all_matching_sender_branches(tmp_path) -> None:
    fetcher = build_fetcher(
        filters={
            "payment_receipts": {
                "any": [
                    {"sender": "receipts-a.example"},
                    {"sender": "example"},
                ],
            },
        },
        run_options={"filter": "payment_receipts"},
    )
    fetcher.data_dir = tmp_path
    conn = LogoutConn()
    fetcher._connect_imap = lambda *_: conn
    fetcher._search_emails_by_criteria = lambda _conn, criteria, last_uid, *, max_uid=None: [(101, b"101")]
    fetcher._process_email = lambda _conn, uid_bytes, uid, account, filter_, **_kw: {
        "imap_uid": uid,
        "account": account,
        "filter": filter_,
        "subject": "Receipt",
        "sender": "<noreply@receipts-a.example>",
        "timestamp": "2026-05-23T10:00:00Z",
        "attachments": [],
    }

    fetched = fetcher.fetch_account({"name": "alex", "email": "user@example.com"}, fetcher.run_filters[0])

    assert fetched == 1
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    account_state = state["filters"]["payment_receipts"]["accounts"]["alex"]
    assert account_state["last_uid"] == 101
    assert account_state["last_received_date"] == "2026-05-23"
    assert isinstance(account_state["last_check"], str)
    assert account_state["sha256:1f41d48b64ec678df112ba10117dbc901d7b6d6f12cdb9af992f6bf829ffba2d"] == 101
    assert account_state["sha256:6eac6bb2e0d23ae003061aa000da1a2be5a26746eb499786d3a21312c2745d5a"] == 101


def test_named_filter_resolution_rejects_non_english_schema_key() -> None:
    with pytest.raises(ValueError, match="lowercase English schema keys only"):
        build_fetcher(
            filters={
                "Поручение": {"subject": "Поручение"},
            }
        )


def test_named_filter_resolution_rejects_reserved_default_key() -> None:
    with pytest.raises(ValueError, match='"default" is reserved for ad-hoc runs'):
        build_fetcher(
            filters={
                "default": {"sender": "keeper@telemost.yandex.ru"},
            }
        )


def test_named_filter_resolution_rejects_removed_profiles_key() -> None:
    with pytest.raises(ValueError, match='"profiles" was removed'):
        build_fetcher(
            filters={
                "profiles": {"forms": {"sender": "forms@yandex.ru"}},
            }
        )


def test_cli_overrides_without_filter_do_not_inherit_telemost_filter() -> None:
    fetcher = build_fetcher(
        filters={
            "telemost": {"sender": "keeper@telemost.yandex.ru"},
        },
        run_options={"subject": "Discussion"},
    )

    assert fetcher.run_filters == [{
        "name": "default",
        "enabled": True,
        "subject": "Discussion",
    }]


def test_bare_run_executes_all_enabled_filters() -> None:
    fetcher = build_fetcher(
        filters={
            "telemost": {"sender": "keeper@telemost.yandex.ru"},
            "forms": {"sender": "forms@yandex.ru", "subject": "New response"},
            "disabled_forms": {"sender": "forms-debug@yandex.ru", "enabled": False},
        },
    )

    assert {item["name"] for item in fetcher.run_filters} == {"forms", "telemost"}


def test_explicit_filter_runs_even_if_disabled() -> None:
    fetcher = build_fetcher(
        filters={
            "disabled_forms": {"sender": "forms@yandex.ru", "enabled": False},
        },
        run_options={"filter": "disabled_forms"},
    )

    assert fetcher.run_filters == [{
        "name": "disabled_forms",
        "enabled": False,
        "sender": "forms@yandex.ru",
    }]


def test_cli_overrides_without_filter_ignore_stored_cursor() -> None:
    fetcher = build_fetcher(
        filters={
            "telemost": {"sender": "keeper@telemost.yandex.ru"},
        },
        run_options={"subject": "Discussion"},
        state={"filters": {"telemost": {"accounts": {"alex": {"last_uid": 777}}}}},
    )

    assert fetcher._effective_last_uid("alex", "default") == 1


def test_cli_overrides_with_explicit_filter_keep_filter_cursor() -> None:
    fetcher = build_fetcher(
        filters={
            "telemost": {"sender": "keeper@telemost.yandex.ru"},
        },
        run_options={"filter": "telemost", "subject": "Discussion"},
        state={"filters": {"telemost": {"accounts": {"alex": {"last_uid": 777}}}}},
    )

    assert fetcher._effective_last_uid("alex", "telemost") == 777


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


def test_search_emails_normalizes_yo_in_subject_for_yandex_imap() -> None:
    fetcher = build_fetcher()
    conn = SearchConn(search_result=b"1", uid_lookup={b"1": 41})

    result = fetcher._search_emails(conn, "gosuslugi.ru", 40, subject="Счёт на оплату")

    assert result == [(41, b"41")]
    assert conn.search_calls == [
        (
            "UTF-8",
            (
                b'FROM "gosuslugi.ru"',
                'SUBJECT "Счет на оплату"'.encode("utf-8"),
            ),
        )
    ]


def test_branch_subject_matching_normalizes_yo() -> None:
    assert mail_fetch.EmailFetcher._branch_matches_meta(
        {"subject": "Счёт на оплату"},
        {"subject": "Счет на оплату. Details"},
    )
    assert mail_fetch.EmailFetcher._branch_matches_meta(
        {"subject": "Счет на оплату"},
        {"subject": "Счёт на оплату"},
    )


def test_search_emails_handles_yandex_bytes_only_uid_fetch() -> None:
    fetcher = build_fetcher()
    conn = SearchConn(
        search_result=b"888 5131",
        uid_lookup={b"888": 929, b"5131": 5296},
        bytes_only_uid_fetch=True,
    )

    result = fetcher._search_emails(conn, "Евгений Войтенков", 1)

    assert result == [(929, b"929"), (5296, b"5296")]


def test_fetch_account_dry_run_collects_headers(monkeypatch) -> None:
    header_message = (
        "Subject: =?utf-8?B?0KLQtdGB0YI=?=\r\n"
        "From: news@example.com\r\n"
        "Date: Thu, 12 Mar 2026 10:00:00 +0000\r\n"
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        '<a href="https://disk.yandex.ru/i/abc">file</a> '
        "https://forms.yandex.ru/u/123/"
    )
    conn = HeaderConn(header_message)
    fetcher = build_fetcher()

    fetcher._connect_imap = lambda *_: conn
    fetcher._search_emails = lambda *_args, **_kwargs: [(11, b"11")]
    fetcher._fetch_message_data = (
        lambda conn_arg, uid_bytes, query, **_kwargs: conn_arg.uid("FETCH", uid_bytes, query)
    )

    count = fetcher.fetch_account(
        {"name": "alex", "email": "user@example.com"},
        fetcher.run_filters[0],
        dry_run=True,
    )

    assert count == 0
    assert conn.logged_out is True
    assert fetcher._get_last_uid("alex", "telemost") == 10
    assert conn.calls[-1] == (
        "FETCH",
        (b"11", "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])"),
    )
    assert fetcher.downloaded == [
        {
            "imap_uid": 11,
            "account": "alex",
            "subject": "Тест",
            "sender": "news@example.com",
            "timestamp": "2026-03-12T10:00:00Z",
            "dry_run": True,
            "filter": "telemost",
            "headers": {
                "From": "news@example.com",
                "Subject": "Тест",
                "Date": "Thu, 12 Mar 2026 10:00:00 +0000",
            },
        }
    ]


def test_fetch_account_dry_run_preview_body_reads_body_without_links(monkeypatch) -> None:
    full_message = (
        "Subject: =?utf-8?B?0KLQtdGB0YI=?=\r\n"
        "From: news@example.com\r\n"
        "Date: Thu, 12 Mar 2026 10:00:00 +0000\r\n"
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        '<a href="https://disk.yandex.ru/i/abc">file</a> '
        "https://forms.yandex.ru/u/123/"
    )
    conn = HeaderConn(full_message)
    fetcher = build_fetcher(run_options={"preview_body": True})

    fetcher._connect_imap = lambda *_: conn
    fetcher._search_emails = lambda *_args, **_kwargs: [(11, b"11")]
    fetcher._fetch_message_data = (
        lambda conn_arg, uid_bytes, query, **_kwargs: conn_arg.uid("FETCH", uid_bytes, query)
    )

    count = fetcher.fetch_account(
        {"name": "alex", "email": "user@example.com"},
        fetcher.run_filters[0],
        dry_run=True,
    )

    assert count == 0
    assert conn.calls[-1] == ("FETCH", (b"11", "(RFC822)"))
    assert fetcher.downloaded == [
        {
            "imap_uid": 11,
            "account": "alex",
            "subject": "Тест",
            "sender": "news@example.com",
            "timestamp": "2026-03-12T10:00:00Z",
            "dry_run": True,
            "filter": "telemost",
            "headers": {
                "From": "news@example.com",
                "Subject": "Тест",
                "Date": "Thu, 12 Mar 2026 10:00:00 +0000",
            },
            "body": {
                "text": "file https://forms.yandex.ru/u/123/",
                "html": '<a href="https://disk.yandex.ru/i/abc">file</a> https://forms.yandex.ru/u/123/',
            },
        }
    ]


def test_cli_dry_run_includes_headers(monkeypatch, capsys) -> None:
    class FakeFetcher:
        active_filter = {"name": "default"}
        run_filters = [{"name": "default"}]
        account_counts = {"alex": 0}
        filter_counts = {"default": 0}

        def fetch_all(self, num_messages=None, dry_run=False):
            assert dry_run is True
            return [
                {
                    "imap_uid": 11,
                    "account": "alex",
                    "sender": "news@example.com",
                    "subject": "Header Test",
                    "timestamp": "2026-03-12T10:00:00Z",
                    "filter": "default",
                    "headers": {"To": "user@example.com", "Subject": "Header Test"},
                }
            ]

        def _should_persist_state(self, *, dry_run=False):
            return not dry_run

        def _get_output_max_inline_symbols(self):
            return 9999

    monkeypatch.setattr(mail_fetch, "EmailFetcher", lambda **_kwargs: FakeFetcher())

    monkeypatch.setattr(sys, "argv", ["fetch_emails.py", "--dry-run", "--subject", "Header Test"])

    mail_fetch.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["pending"][0]["headers"] == {
        "To": "user@example.com",
        "Subject": "Header Test",
    }


def test_fetch_account_dry_run_does_not_sleep(monkeypatch) -> None:
    conn = HeaderConn(
        "Subject: Test\r\nFrom: news@example.com\r\nDate: Thu, 12 Mar 2026 10:00:00 +0000\r\n\r\n"
    )
    fetcher = build_fetcher()
    fetcher.config["mail"]["fetch"] = {"sleep_seconds": 99}

    monkeypatch.setattr(
        mail_fetch.time,
        "sleep",
        lambda *_args, **_kwargs: pytest.fail("dry-run must not sleep"),
    )
    fetcher._connect_imap = lambda *_: conn
    fetcher._search_emails = lambda *_args, **_kwargs: [(11, b"11"), (12, b"12")]
    fetcher._fetch_message_data = (
        lambda conn_arg, uid_bytes, query, **_kwargs: conn_arg.uid("FETCH", uid_bytes, query)
    )

    count = fetcher.fetch_account(
        {"name": "alex", "email": "user@example.com"},
        fetcher.run_filters[0],
        dry_run=True,
    )

    assert count == 0


def test_process_email_persists_filter_under_filter_directory(tmp_path) -> None:
    class FullMessageConn:
        def uid(self, command, *_args):
            assert command == "FETCH"
            raw = (
                b"From: news@example.com\r\n"
                b"Subject: Test\r\n"
                b"Date: Thu, 12 Mar 2026 10:00:00 +0000\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n"
                b"\r\n"
                b"hello"
            )
            return "OK", [(b"1", raw)]

    fetcher = build_fetcher()
    fetcher.data_dir = tmp_path

    meta = fetcher._process_email(FullMessageConn(), b"1", 11, "alex", "forms")

    assert meta is not None
    assert meta["filter"] == "forms"
    assert meta["dir_name"] == "2026-03-12_alex_uid11"
    assert meta["dir_relpath"] == "forms/2026-03-12_alex_uid11"
    meta_path = tmp_path / "incoming" / "forms" / "2026-03-12_alex_uid11" / "meta.json"
    assert meta_path.exists()
    saved = json.loads(meta_path.read_text(encoding="utf-8"))
    assert saved["filter"] == "forms"
    assert saved["dir_relpath"] == "forms/2026-03-12_alex_uid11"
    assert saved["headers"] == {
        "From": "news@example.com",
        "Subject": "Test",
        "Date": "Thu, 12 Mar 2026 10:00:00 +0000",
    }

def test_process_email_keeps_body_separate_and_writes_attachment_objects(tmp_path) -> None:
    raw = b"\r\n".join(
        [
            b"From: news@example.com",
            b"Subject: Parts",
            b"Date: Thu, 12 Mar 2026 10:00:00 +0000",
            b"Content-Type: multipart/mixed; boundary=outer",
            b"",
            b"--outer",
            b"Content-Type: text/plain; charset=utf-8",
            b"Content-Disposition: inline",
            b"",
            b"plain body",
            b"--outer",
            b"Content-Type: text/html; charset=utf-8",
            b"Content-Disposition: inline",
            b"",
            b"<p>html body</p>",
            b"--outer",
            b"Content-Type: application/pdf",
            b"Content-Disposition: attachment; filename=invoice.pdf",
            b"Content-Transfer-Encoding: base64",
            b"",
            b"cGRmLWJ5dGVz",
            b"--outer",
            b"Content-Type: image/png",
            b"Content-Disposition: inline; filename=logo.png",
            b"Content-ID: <logo@cid>",
            b"Content-Transfer-Encoding: base64",
            b"",
            b"cG5nLWJ5dGVz",
            b"--outer--",
            b"",
        ]
    )

    class FullMessageConn:
        def uid(self, command, *_args):
            assert command == "FETCH"
            return "OK", [(b"1", raw)]

    fetcher = build_fetcher()
    fetcher.data_dir = tmp_path

    meta = fetcher._process_email(FullMessageConn(), b"1", 11, "alex", "forms")

    assert meta is not None
    email_dir = tmp_path / "incoming" / "forms" / "2026-03-12_alex_uid11"
    assert (email_dir / "email_body.txt").read_text(encoding="utf-8") == "plain body"
    assert (email_dir / "email_body.html").read_text(encoding="utf-8") == "<p>html body</p>"
    assert (email_dir / "invoice.pdf").read_bytes() == b"pdf-bytes"
    assert (email_dir / "logo.png").read_bytes() == b"png-bytes"
    assert meta["body"] == {"text": "email_body.txt", "html": "email_body.html"}
    assert "attachment_details" not in meta
    assert "inline_assets" not in meta
    assert meta["attachments"] == [
        {
            "original-filename": "invoice.pdf",
            "saved-filename": "invoice.pdf",
            "content-type": "application/pdf",
            "size": len(b"pdf-bytes"),
            "disposition": "attachment",
            "content-id": None,
            "part-index": 3,
        },
        {
            "original-filename": "logo.png",
            "saved-filename": "logo.png",
            "content-type": "image/png",
            "size": len(b"png-bytes"),
            "disposition": "inline",
            "content-id": "<logo@cid>",
            "part-index": 4,
        },
    ]


def test_normalize_attachments_meta_accepts_legacy_strings() -> None:
    assert mail_fetch.EmailFetcher._normalize_attachments_meta(["invoice.pdf"]) == [
        {
            "original-filename": "invoice.pdf",
            "saved-filename": "invoice.pdf",
            "content-type": None,
            "size": None,
            "disposition": None,
            "content-id": None,
            "part-index": None,
        }
    ]


def test_process_email_avoids_attachment_filename_collisions(tmp_path) -> None:
    raw = b"\r\n".join(
        [
            b"From: news@example.com",
            b"Subject: Duplicate attachments",
            b"Date: Thu, 12 Mar 2026 10:00:00 +0000",
            b"Content-Type: multipart/mixed; boundary=outer",
            b"",
            b"--outer",
            b"Content-Type: text/plain; charset=utf-8",
            b"",
            b"body",
            b"--outer",
            b"Content-Type: application/octet-stream",
            b"Content-Disposition: attachment; filename=file.txt",
            b"Content-Transfer-Encoding: base64",
            b"",
            b"b25l",
            b"--outer",
            b"Content-Type: application/octet-stream",
            b"Content-Disposition: attachment; filename=file.txt",
            b"Content-Transfer-Encoding: base64",
            b"",
            b"dHdv",
            b"--outer--",
            b"",
        ]
    )

    class FullMessageConn:
        def uid(self, command, *_args):
            assert command == "FETCH"
            return "OK", [(b"1", raw)]

    fetcher = build_fetcher()
    fetcher.data_dir = tmp_path

    meta = fetcher._process_email(FullMessageConn(), b"1", 11, "alex", "forms")

    assert meta is not None
    email_dir = tmp_path / "incoming" / "forms" / "2026-03-12_alex_uid11"
    assert (email_dir / "file.txt").read_bytes() == b"one"
    assert (email_dir / "file-2.txt").read_bytes() == b"two"
    assert [item["saved-filename"] for item in meta["attachments"]] == [
        "file.txt",
        "file-2.txt",
    ]
    assert [item["original-filename"] for item in meta["attachments"]] == [
        "file.txt",
        "file.txt",
    ]

def test_extract_message_bytes_accepts_direct_bytes_payload() -> None:
    raw_header = b"From: news@example.com\r\nSubject: Test\r\nDate: Thu, 12 Mar 2026 10:00:00 +0000\r\n\r\n"

    extracted = mail_fetch.EmailFetcher._extract_message_bytes([raw_header])

    assert extracted == raw_header


def test_fetch_account_from_uid_is_non_persistent(monkeypatch) -> None:
    fetcher = build_fetcher(run_options={"from_uid": 5000})
    conn = LogoutConn()
    save_calls = []

    fetcher._connect_imap = lambda *_: conn
    fetcher._search_emails = lambda *_args, **_kwargs: [(5001, b"5001")]
    fetcher._process_email = lambda *_args, **_kwargs: {
        "imap_uid": 5001,
        "account": "alex",
        "subject": "Backfill",
        "sender": "user@example.com",
        "timestamp": "2026-03-12T10:00:00Z",
        "attachments": [],
        "dir_name": "2026-03-12_alex_uid5001",
    }
    fetcher._save_state = lambda: save_calls.append("saved")

    fetched = fetcher.fetch_account({"name": "alex", "email": "user@example.com"}, fetcher.run_filters[0])

    assert fetched == 1
    assert fetcher._get_last_uid("alex", "telemost") == 10
    assert save_calls == []
    assert conn.logged_out is True


def test_fetch_account_uid_fetches_exact_message_without_search() -> None:
    fetcher = build_fetcher(
        accounts=[{"name": "alex", "email": "user@example.com"}],
        run_options={"uid": 5000},
    )
    conn = LogoutConn()
    processed = []

    fetcher._connect_imap = lambda *_: conn
    fetcher._search_emails = lambda *_args, **_kwargs: pytest.fail("--uid must skip search")
    fetcher._process_email = lambda _conn, uid_bytes, uid, account, filter_, **_kw: (
        processed.append((uid_bytes, uid, account, filter_))
        or {"imap_uid": uid, "subject": "Exact", "attachments": []}
    )
    fetcher._save_state = lambda: pytest.fail("--uid must not persist")

    fetched = fetcher.fetch_account({"name": "alex", "email": "user@example.com"}, fetcher.run_filters[0])

    assert fetched == 1
    assert processed == [(b"5000", 5000, "alex", "default")]
    assert conn.logged_out is True


def test_fetch_all_respects_global_cap() -> None:
    fetcher = build_fetcher()

    calls = []

    def fake_fetch_account(account_config, run_filter, max_messages=None, dry_run=False):
        calls.append((account_config["name"], run_filter["name"], max_messages, dry_run))
        fetcher.downloaded.append({"account": account_config["name"], "filter": run_filter["name"]})
        return 1

    fetcher.fetch_account = fake_fetch_account

    downloaded = fetcher.fetch_all(num_messages=1, dry_run=False)

    assert calls == [("alex", "telemost", 1, False)]
    assert fetcher.account_counts == {"alex": 1, "beta": 0}
    assert fetcher.filter_counts == {"telemost": 1}
    assert downloaded == [{"account": "alex", "filter": "telemost"}]


def test_fetch_all_restricts_account_selection() -> None:
    fetcher = build_fetcher(run_options={"account": "beta"})
    calls = []
    fetcher.fetch_account = (
        lambda account_config, run_filter, **kwargs: calls.append((account_config["name"], run_filter["name"])) or 0
    )

    fetcher.fetch_all()

    assert calls == [("beta", "telemost")]


def test_fetch_all_rejects_unknown_account() -> None:
    fetcher = build_fetcher(run_options={"account": "missing"})

    with pytest.raises(ValueError, match='Unknown account alias "missing"'):
        fetcher.fetch_all()


def test_fetch_all_rejects_uid_without_unambiguous_account() -> None:
    fetcher = build_fetcher(run_options={"uid": 42})

    with pytest.raises(ValueError, match="--uid requires --account"):
        fetcher.fetch_all()


def test_main_spills_heavy_pending_output_to_file(monkeypatch, tmp_path, capsys) -> None:
    seen_kwargs = {}

    class FakeFetcher:
        def __init__(self, **kwargs):
            seen_kwargs.update(kwargs)
            self.active_filter = {"name": "telemost"}
            self.run_filters = [{"name": "telemost"}]
            self.account_counts = {"beta": 3}
            self.filter_counts = {"telemost": 2}
            self.data_dir = tmp_path
            self.config = {"mail": {"output": {"max_inline_symbols": 10}}}

        def fetch_all(self, num_messages=None, dry_run=False):
            assert num_messages is None
            assert dry_run is True
            return [
                {
                    "imap_uid": 1,
                    "account": "beta",
                    "sender": "alice@example.com",
                    "subject": "Long enough subject 1",
                    "timestamp": "2026-03-12T10:00:00Z",
                    "filter": "telemost",
                },
                {
                    "imap_uid": 2,
                    "account": "beta",
                    "sender": "bob@example.com",
                    "subject": "Long enough subject 2",
                    "timestamp": "2026-03-13T10:00:00Z",
                    "filter": "telemost",
                },
            ]

        def _should_persist_state(self, *, dry_run):
            return not dry_run

        def _get_output_max_inline_symbols(self):
            return 10

        def _spill_payload_to_file(self, payload, *, prefix):
            output_path = tmp_path / f"{prefix}.json"
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return output_path

    monkeypatch.setattr(mail_fetch, "EmailFetcher", FakeFetcher)
    monkeypatch.setattr(sys, "argv", ["fetch_emails.py", "--dry-run"])

    mail_fetch.main()

    captured = json.loads(capsys.readouterr().out)
    assert captured["filter"] == "telemost"
    assert captured["filters"] == ["telemost"]
    assert captured["filter_counts"] == {"telemost": 2}
    assert captured["pending_total"] == 2
    assert captured["preview_body"] is False
    assert seen_kwargs["preview_body"] is False
    assert captured["pending"] == []
    assert captured["output_spilled"] is True
    assert captured["inline_threshold_symbols"] == 10
    assert captured["output_file"].endswith("mail_dry_run.json")
    assert "Copy this file if you need to keep it." in captured["output_notice"]
    assert Path(captured["output_file"]).exists()


def test_main_preview_body_requires_dry_run(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["fetch_emails.py", "--preview-body"])

    with pytest.raises(SystemExit) as excinfo:
        mail_fetch.main()

    assert excinfo.value.code == 2


def test_main_dry_run_preview_body_includes_body(monkeypatch, capsys) -> None:
    seen_kwargs = {}

    class FakeFetcher:
        def __init__(self, **kwargs):
            seen_kwargs.update(kwargs)
            self.active_filter = {"name": "telemost"}
            self.run_filters = [{"name": "telemost"}]
            self.account_counts = {"beta": 1}
            self.filter_counts = {"telemost": 1}
            self.config = {"mail": {"output": {"max_inline_symbols": 10000}}}

        def fetch_all(self, num_messages=None, dry_run=False):
            assert dry_run is True
            return [
                {
                    "imap_uid": 1,
                    "account": "beta",
                    "sender": "alice@example.com",
                    "subject": "Preview",
                    "timestamp": "2026-03-12T10:00:00Z",
                    "filter": "telemost",
                    "body": {"text": "hello", "html": "<p>hello</p>"},
                }
            ]

        def _should_persist_state(self, *, dry_run):
            return not dry_run

        def _get_output_max_inline_symbols(self):
            return 10000

    monkeypatch.setattr(mail_fetch, "EmailFetcher", FakeFetcher)
    monkeypatch.setattr(sys, "argv", ["fetch_emails.py", "--dry-run", "--preview-body"])

    mail_fetch.main()

    captured = json.loads(capsys.readouterr().out)
    assert seen_kwargs["preview_body"] is True
    assert captured["preview_body"] is True
    assert captured["pending"] == [
        {
            "uid": 1,
            "account": "beta",
            "sender": "alice@example.com",
            "subject": "Preview",
            "timestamp": "2026-03-12T10:00:00Z",
            "filter": "telemost",
            "body": {"text": "hello", "html": "<p>hello</p>"},
        }
    ]


def test_spill_payload_replaces_previous_artifact(tmp_path) -> None:
    fetcher = build_fetcher()
    fetcher.data_dir = tmp_path
    fetcher.config["mail"]["output"] = {"spill_dir": "latest-query"}

    first = fetcher._spill_payload_to_file({"pending": [1]}, prefix="mail_dry_run")
    second = fetcher._spill_payload_to_file({"pending": [2]}, prefix="mail_dry_run")

    assert not first.exists()
    assert second.exists()
    assert list((tmp_path / "latest-query").glob("*.json")) == [second]
