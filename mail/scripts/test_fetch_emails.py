#!/usr/bin/env python3
"""Regression tests for the Yandex Mail fetcher."""

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
            {"name": "work", "email": "work@example.com"},
        ],
    }
    fetcher.data_dir = Path("/tmp/yandex-data")
    fetcher.state = state or {"filters": {"telemost": {"mailboxes": {"alex": {"last_uid": 10}}}}}
    fetcher.downloaded = []
    fetcher.mailbox_counts = {}
    fetcher.filter_counts = {}
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
    fetcher.named_filters = fetcher._resolve_named_filters()
    fetcher.run_filters = fetcher._resolve_run_filters()
    fetcher.active_filter = fetcher.run_filters[0] if len(fetcher.run_filters) == 1 else None
    return fetcher


def test_to_imap_date_normalizes_iso_date() -> None:
    assert mail_fetch.EmailFetcher._to_imap_date("2026-03-12") == "12-Mar-2026"
    assert mail_fetch.EmailFetcher._to_imap_date("12-Mar-2026") == "12-Mar-2026"
    assert mail_fetch.EmailFetcher._to_imap_date("bad-date") is None


def test_legacy_state_normalizes_to_telemost_filter() -> None:
    fetcher = build_fetcher()
    normalized = fetcher._normalize_state({"mailboxes": {"alex": {"last_uid": 9}}})

    assert normalized == {"filters": {"telemost": {"mailboxes": {"alex": {"last_uid": 9}}}}}


def test_bad_intermediate_default_state_normalizes_to_telemost_filter() -> None:
    fetcher = build_fetcher()
    normalized = fetcher._normalize_state({"filters": {"default": {"mailboxes": {"alex": {"last_uid": 9}}}}})

    assert normalized == {"filters": {"telemost": {"mailboxes": {"alex": {"last_uid": 9}}}}}


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
        state={"filters": {"telemost": {"mailboxes": {"alex": {"last_uid": 777}}}}},
    )

    assert fetcher._effective_last_uid("alex", "default") == 1


def test_cli_overrides_with_explicit_filter_keep_filter_cursor() -> None:
    fetcher = build_fetcher(
        filters={
            "telemost": {"sender": "keeper@telemost.yandex.ru"},
        },
        run_options={"filter": "telemost", "subject": "Discussion"},
        state={"filters": {"telemost": {"mailboxes": {"alex": {"last_uid": 777}}}}},
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


def test_search_emails_handles_yandex_bytes_only_uid_fetch() -> None:
    fetcher = build_fetcher()
    conn = SearchConn(
        search_result=b"888 5131",
        uid_lookup={b"888": 929, b"5131": 5296},
        bytes_only_uid_fetch=True,
    )

    result = fetcher._search_emails(conn, "Евгений Войтенков", 1)

    assert result == [(929, b"929"), (5296, b"5296")]


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
        fetcher.run_filters[0],
        dry_run=True,
    )

    assert count == 0
    assert conn.logged_out is True
    assert fetcher._get_last_uid("alex", "telemost") == 10
    assert fetcher.downloaded == [
        {
            "imap_uid": 11,
            "mailbox": "alex",
            "subject": "Тест",
            "sender": "news@example.com",
            "timestamp": "2026-03-12T10:00:00Z",
            "dry_run": True,
            "filter": "telemost",
        }
    ]


def test_fetch_mailbox_dry_run_does_not_sleep(monkeypatch) -> None:
    conn = HeaderConn(
        "Subject: Test\r\nFrom: news@example.com\r\nDate: Thu, 12 Mar 2026 10:00:00 +0000\r\n\r\n"
    )
    fetcher = build_fetcher()
    fetcher.config["mail"]["fetch"] = {"sleep_seconds": 99}

    monkeypatch.setattr(
        mail_fetch,
        "resolve_token",
        lambda **_: SimpleNamespace(token="y0_mail"),
    )
    monkeypatch.setattr(
        mail_fetch.time,
        "sleep",
        lambda *_args, **_kwargs: pytest.fail("dry-run must not sleep"),
    )
    fetcher._connect_imap = lambda *_: conn
    fetcher._search_emails = lambda *_args, **_kwargs: [(11, b"11"), (12, b"12")]

    count = fetcher.fetch_mailbox(
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


def test_extract_message_bytes_accepts_direct_bytes_payload() -> None:
    raw_header = b"From: news@example.com\r\nSubject: Test\r\nDate: Thu, 12 Mar 2026 10:00:00 +0000\r\n\r\n"

    extracted = mail_fetch.EmailFetcher._extract_message_bytes([raw_header])

    assert extracted == raw_header


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

    fetched = fetcher.fetch_mailbox({"name": "alex", "email": "user@example.com"}, fetcher.run_filters[0])

    assert fetched == 1
    assert fetcher._get_last_uid("alex", "telemost") == 10
    assert save_calls == []
    assert conn.logged_out is True


def test_fetch_all_respects_global_cap() -> None:
    fetcher = build_fetcher()

    calls = []

    def fake_fetch_mailbox(mailbox_config, run_filter, max_messages=None, dry_run=False):
        calls.append((mailbox_config["name"], run_filter["name"], max_messages, dry_run))
        fetcher.downloaded.append({"mailbox": mailbox_config["name"], "filter": run_filter["name"]})
        return 1

    fetcher.fetch_mailbox = fake_fetch_mailbox

    downloaded = fetcher.fetch_all(num_messages=1, dry_run=False)

    assert calls == [("alex", "telemost", 1, False)]
    assert fetcher.mailbox_counts == {"alex": 1, "work": 0}
    assert fetcher.filter_counts == {"telemost": 1}
    assert downloaded == [{"mailbox": "alex", "filter": "telemost"}]


def test_fetch_all_restricts_mailbox_selection() -> None:
    fetcher = build_fetcher(run_options={"mailbox": "work"})
    calls = []
    fetcher.fetch_mailbox = (
        lambda mailbox_config, run_filter, **kwargs: calls.append((mailbox_config["name"], run_filter["name"])) or 0
    )

    fetcher.fetch_all()

    assert calls == [("work", "telemost")]


def test_fetch_all_rejects_unknown_mailbox() -> None:
    fetcher = build_fetcher(run_options={"mailbox": "missing"})

    with pytest.raises(ValueError, match='Unknown mailbox "missing"'):
        fetcher.fetch_all()


def test_main_spills_heavy_pending_output_to_file(monkeypatch, tmp_path, capsys) -> None:
    class FakeFetcher:
        def __init__(self, **_kwargs):
            self.active_filter = {"name": "telemost"}
            self.run_filters = [{"name": "telemost"}]
            self.mailbox_counts = {"work": 3}
            self.filter_counts = {"telemost": 2}
            self.data_dir = tmp_path
            self.config = {"mail": {"output": {"max_inline_symbols": 10}}}

        def fetch_all(self, num_messages=None, dry_run=False):
            assert num_messages is None
            assert dry_run is True
            return [
                {
                    "imap_uid": 1,
                    "mailbox": "work",
                    "sender": "alice@example.com",
                    "subject": "Long enough subject 1",
                    "timestamp": "2026-03-12T10:00:00Z",
                    "filter": "telemost",
                },
                {
                    "imap_uid": 2,
                    "mailbox": "work",
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
    assert captured["pending"] == []
    assert captured["output_spilled"] is True
    assert captured["inline_threshold_symbols"] == 10
    assert captured["output_file"].endswith("mail_dry_run.json")
    assert "Copy this file if you need to keep it." in captured["output_notice"]
    assert Path(captured["output_file"]).exists()


def test_spill_payload_replaces_previous_artifact(tmp_path) -> None:
    fetcher = build_fetcher()
    fetcher.data_dir = tmp_path
    fetcher.config["mail"]["output"] = {"spill_dir": "latest-query"}

    first = fetcher._spill_payload_to_file({"pending": [1]}, prefix="mail_dry_run")
    second = fetcher._spill_payload_to_file({"pending": [2]}, prefix="mail_dry_run")

    assert not first.exists()
    assert second.exists()
    assert list((tmp_path / "latest-query").glob("*.json")) == [second]
