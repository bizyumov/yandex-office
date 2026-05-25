#!/usr/bin/env python3
"""Regression tests for the Yandex Mail sender."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import send_email as mail_send
from common.api import TokenRef, method_auth


def build_sender(*, config: dict | None = None) -> mail_send.EmailSender:
    """Construct an EmailSender without calling load_runtime_context."""
    sender = mail_send.EmailSender.__new__(mail_send.EmailSender)
    sender.config = config or {
        "smtp": {"server": "smtp.yandex.com", "port": 465},
        "imap": {"server": "imap.yandex.com", "port": 993},
    }
    sender.data_dir = Path("/tmp/yandex-data")
    return sender


def make_ctx(
    *,
    email: str = "sender@example.com",
    token: str = "test-token",
    account: str | None = None,
) -> mail_send.YandexApiContext:
    """Build a real YandexApiContext with mock token data."""
    token_ref = TokenRef(
        token=token,
        client_id="test-client-id",
        source_key="test-token-key",
        good_at=None,
        bad_at=None,
    )
    return mail_send.YandexApiContext(
        account=account,
        data_dir=Path("/tmp/yandex-data"),
        config={"smtp": {"server": "smtp.yandex.com", "port": 465}},
        session=MagicMock(),
        token_ref=token_ref,
        token_data={"email": email},
    )


def test_no_app_password_runtime_helpers_remain() -> None:
    assert not hasattr(mail_send, "_parse_env_file")
    assert not hasattr(mail_send, "_resolve_credentials_file")
    assert not hasattr(mail_send, "_load_app_password")
    assert not hasattr(mail_send, "_connect_smtp_app_password")


def test_smtp_send_decorator_requires_mail_smtp() -> None:
    auth = method_auth(mail_send.EmailSender._connect_smtp_oauth2)
    assert auth.method_id == "mail.smtp.send"
    assert auth.one_of == ("mail:smtp",)
    assert auth.all_of == ()
    assert not auth.public


def test_mail_credentials_extracts_email_and_token() -> None:
    ctx = make_ctx(email="user@yandex.ru", token="abc123")
    email_addr, token = mail_send.EmailSender._mail_credentials(ctx)
    assert email_addr == "user@yandex.ru"
    assert token == "abc123"


def test_mail_credentials_raises_on_missing_token_ref() -> None:
    ctx = mail_send.YandexApiContext(
        account=None,
        data_dir=Path("/tmp"),
        config={},
        session=MagicMock(),
        token_ref=None,
        token_data=None,
    )
    with pytest.raises(RuntimeError, match="not token-bound"):
        mail_send.EmailSender._mail_credentials(ctx)


def test_mail_credentials_raises_on_missing_email() -> None:
    ref = TokenRef(token="t", client_id="c", source_key="k", good_at=None, bad_at=None)
    ctx = mail_send.YandexApiContext(
        account=None,
        data_dir=Path("/tmp"),
        config={},
        session=MagicMock(),
        token_ref=ref,
        token_data={},
    )
    with pytest.raises(RuntimeError, match="missing verified email"):
        mail_send.EmailSender._mail_credentials(ctx)


@patch("send_email.smtplib.SMTP_SSL")
def test_connect_smtp_oauth2_authenticates_with_xoauth2(mock_smtp_cls: MagicMock) -> None:
    mock_conn = MagicMock()
    mock_conn.docmd.return_value = (235, b"2.0.0 OK")
    mock_smtp_cls.return_value = mock_conn

    sender = build_sender()
    ctx = make_ctx(email="user@yandex.ru", token="ya-token")

    original = sender._connect_smtp_oauth2.__wrapped__  # type: ignore[attr-defined]
    result = original(sender, ctx)

    assert isinstance(result, mail_send.SmtpSendResult)
    assert result.sender_email == "user@yandex.ru"
    assert result.conn is mock_conn
    mock_smtp_cls.assert_called_once()

    docmd_call = mock_conn.docmd.call_args
    assert docmd_call[0][0] == "AUTH"
    auth_value = docmd_call[0][1]
    assert auth_value.startswith("XOAUTH2 ")
    decoded = base64.b64decode(auth_value.removeprefix("XOAUTH2 ")).decode()
    assert decoded == "user=user@yandex.ru\x01auth=Bearer ya-token\x01\x01"


@patch("send_email.smtplib.SMTP_SSL")
def test_connect_smtp_oauth2_raises_on_auth_failure(mock_smtp_cls: MagicMock) -> None:
    mock_conn = MagicMock()
    mock_smtp_cls.return_value = mock_conn
    mock_conn.docmd.return_value = (535, b"5.7.8 Error: authentication failed")

    sender = build_sender()
    ctx = make_ctx(email="user@yandex.ru", token="bad-token")

    original = sender._connect_smtp_oauth2.__wrapped__  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="SMTP XOAUTH2 auth failed"):
        original(sender, ctx)

    mock_conn.quit.assert_called_once()


def test_connect_smtp_uses_managed_oauth_context() -> None:
    mock_conn = MagicMock()
    sender = build_sender()

    with patch.object(sender, "_connect_smtp_oauth2") as mock_oauth2:
        mock_oauth2.return_value = mail_send.SmtpSendResult(
            conn=mock_conn,
            sender_email="user@yandex.ru",
        )
        result = sender._connect_smtp(account="alex")

    assert result.sender_email == "user@yandex.ru"
    mock_oauth2.assert_called_once()
    ctx = mock_oauth2.call_args.kwargs["ctx"]
    assert ctx.account == "alex"
    assert ctx.data_dir == sender.data_dir


@patch("send_email.smtplib.SMTP_SSL")
def test_send_builds_correct_message(mock_smtp_cls: MagicMock) -> None:
    mock_conn = MagicMock()
    mock_conn.docmd.return_value = (235, b"2.0.0 OK")
    mock_smtp_cls.return_value = mock_conn

    sender = build_sender()

    with patch.object(sender, "_connect_smtp") as mock_connect:
        mock_connect.return_value = mail_send.SmtpSendResult(
            conn=mock_conn,
            sender_email="sender@yandex.ru",
        )
        result = sender.send(
            to="recipient@example.com",
            subject="Test Subject",
            body="Hello World",
        )

    assert result["status"] == "sent"
    assert result["from"] == "sender@yandex.ru"
    assert result["to"] == ["recipient@example.com"]
    assert result["subject"] == "Test Subject"

    mock_conn.send_message.assert_called_once()
    msg = mock_conn.send_message.call_args.args[0]
    assert msg["To"] == "recipient@example.com"
    assert msg["Subject"] == "Test Subject"
    assert msg["From"] == "sender@yandex.ru"
    assert mock_conn.send_message.call_args.kwargs["from_addr"] == "sender@yandex.ru"
    assert mock_conn.send_message.call_args.kwargs["to_addrs"] == [
        "recipient@example.com",
    ]


@patch("send_email.smtplib.SMTP_SSL")
def test_send_with_cc_and_bcc_uses_explicit_envelope(mock_smtp_cls: MagicMock) -> None:
    mock_conn = MagicMock()
    mock_conn.docmd.return_value = (235, b"OK")
    mock_smtp_cls.return_value = mock_conn

    sender = build_sender()

    with patch.object(sender, "_connect_smtp") as mock_connect:
        mock_connect.return_value = mail_send.SmtpSendResult(
            conn=mock_conn,
            sender_email="s@yandex.ru",
        )
        result = sender.send(
            to=["a@example.com", "b@example.com"],
            subject="Multi",
            body="Body",
            cc="cc@example.com",
            bcc="secret@example.com",
            reply_to="reply@example.com",
        )

    assert result["to"] == ["a@example.com", "b@example.com"]
    assert result["cc"] == ["cc@example.com"]
    assert result["bcc"] == ["secret@example.com"]
    assert result["reply_to"] == "reply@example.com"

    call = mock_conn.send_message.call_args
    msg = call.args[0]
    assert msg["To"] == "a@example.com, b@example.com"
    assert msg["Cc"] == "cc@example.com"
    assert msg["Reply-To"] == "reply@example.com"
    assert "Bcc" not in msg
    assert call.kwargs["to_addrs"] == [
        "a@example.com",
        "b@example.com",
        "cc@example.com",
        "secret@example.com",
    ]


@patch("send_email.smtplib.SMTP_SSL")
def test_send_html_content_type(mock_smtp_cls: MagicMock) -> None:
    mock_conn = MagicMock()
    mock_smtp_cls.return_value = mock_conn

    sender = build_sender()

    with patch.object(sender, "_connect_smtp") as mock_connect:
        mock_connect.return_value = mail_send.SmtpSendResult(
            conn=mock_conn,
            sender_email="s@y.ru",
        )
        sender.send(
            to="a@b.com",
            subject="HTML",
            body="<h1>Hello</h1>",
            content_type="html",
        )

    msg = mock_conn.send_message.call_args.args[0]
    assert msg.get_content_type() == "text/html"


def test_cli_returns_error_without_body() -> None:
    ret = mail_send.main(["--to", "a@b.com", "--subject", "Test"])
    assert ret == 1


def test_cli_body_file_reads_content(tmp_path: Path) -> None:
    body_file = tmp_path / "body.txt"
    body_file.write_text("File body content", encoding="utf-8")

    with patch.object(mail_send.EmailSender, "send") as mock_send:
        mock_send.return_value = {
            "status": "sent",
            "from": "s@y.ru",
            "to": ["a@b.com"],
            "subject": "Test",
            "message_id": "123",
        }
        init_calls: list[dict] = []

        def fake_init(self, **kwargs):
            init_calls.append(kwargs)

        with patch.object(mail_send.EmailSender, "__init__", fake_init):
            ret = mail_send.main(
                [
                    "--account",
                    "alex",
                    "--to",
                    "a@b.com",
                    "--subject",
                    "Test",
                    "--body-file",
                    str(body_file),
                    "--data-dir",
                    str(tmp_path),
                    "--verbose",
                ]
            )

    assert ret == 0
    call_kwargs = mock_send.call_args.kwargs
    assert init_calls == [{"data_dir": str(tmp_path)}]
    assert call_kwargs["account"] == "alex"
    assert call_kwargs["body"] == "File body content"


def test_cli_json_output(capsys) -> None:
    with patch.object(mail_send.EmailSender, "send") as mock_send:
        mock_send.return_value = {
            "status": "sent",
            "from": "s@y.ru",
            "to": ["a@b.com"],
            "subject": "Test",
            "message_id": "123",
        }
        with patch.object(mail_send.EmailSender, "__init__", lambda self, **kw: None):
            ret = mail_send.main(
                [
                    "--account",
                    "alex",
                    "--to",
                    "a@b.com",
                    "--cc",
                    "c@b.com",
                    "--bcc",
                    "hidden@b.com",
                    "--reply-to",
                    "reply@b.com",
                    "--subject",
                    "Test",
                    "--body",
                    "<p>Hello</p>",
                    "--content-type",
                    "html",
                    "--format",
                    "json",
                ]
            )

    assert ret == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "sent"
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["account"] == "alex"
    assert call_kwargs["cc"] == ["c@b.com"]
    assert call_kwargs["bcc"] == ["hidden@b.com"]
    assert call_kwargs["reply_to"] == "reply@b.com"
    assert call_kwargs["content_type"] == "html"
