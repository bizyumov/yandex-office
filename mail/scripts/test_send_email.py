#!/usr/bin/env python3
"""Regression tests for the Yandex Mail sender."""

from __future__ import annotations

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


def build_sender(
    *,
    config: dict | None = None,
) -> mail_send.EmailSender:
    """Construct an EmailSender without calling load_runtime_context."""
    sender = mail_send.EmailSender.__new__(mail_send.EmailSender)
    sender.config = config or {
        "smtp": {"server": "smtp.yandex.com", "port": 465},
        "imap": {"server": "imap.yandex.com", "port": 993},
    }
    sender.data_dir = Path("/tmp/yandex-data")
    return sender


class MockTokenRef:
    """Minimal TokenRef-like object for testing."""

    def __init__(self, token: str = "test-token") -> None:
        self.token = token
        self.client_id = "test-client-id"
        self.source_key = "test-token-key"
        self.good_at = None
        self.bad_at = None


def make_ctx(
    *,
    email: str = "sender@example.com",
    token: str = "test-token",
    account: str | None = None,
) -> mail_send.YandexApiContext:
    """Build a real YandexApiContext with mock token data for decorator dispatch.

    The decorator dispatches through _dispatch_yandex_api which reads
    account, data_dir, config, session from the context, and then resolves
    token candidates from token files. For unit tests that bypass the
    decorator by calling the original function directly, we just need
    token_ref and token_data.
    """
    from common.api import TokenRef

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


# --- Unit tests ---


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
    from common.api import TokenRef

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
def test_connect_smtp_authenticates_with_xoauth2(mock_smtp_cls: MagicMock) -> None:
    mock_conn = MagicMock()
    mock_conn.docmd.return_value = (235, b"2.0.0 OK")
    mock_smtp_cls.return_value = mock_conn

    sender = build_sender()
    ctx = make_ctx(email="user@yandex.ru", token="ya-token")

    # Call the original unwrapped method directly to bypass decorator dispatch
    original = sender._connect_smtp.__wrapped__  # type: ignore[attr-defined]
    result = original(sender, ctx)

    assert isinstance(result, mail_send.SmtpSendResult)
    assert result.sender_email == "user@yandex.ru"
    assert result.conn is mock_conn

    # Verify XOAUTH2 auth was attempted
    docmd_call = mock_conn.docmd.call_args
    assert docmd_call[0][0] == "AUTH"
    auth_value = docmd_call[0][1]
    assert auth_value.startswith("XOAUTH2 ")


@patch("send_email.smtplib.SMTP_SSL")
def test_connect_smtp_raises_on_auth_failure(mock_smtp_cls: MagicMock) -> None:
    mock_conn = MagicMock()
    mock_smtp_cls.return_value = mock_conn
    mock_conn.docmd.return_value = (535, b"5.7.8 Error: authentication failed")

    sender = build_sender()
    ctx = make_ctx(email="user@yandex.ru", token="bad-token")

    original = sender._connect_smtp.__wrapped__  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="SMTP XOAUTH2 auth failed"):
        original(sender, ctx)

    mock_conn.quit.assert_called_once()


@patch("send_email.smtplib.SMTP_SSL")
def test_send_builds_correct_message(mock_smtp_cls: MagicMock) -> None:
    mock_conn = MagicMock()
    mock_conn.docmd.return_value = (235, b"2.0.0 OK")
    mock_smtp_cls.return_value = mock_conn

    sender = build_sender()

    with patch.object(sender, "_connect_smtp") as mock_connect:
        mock_connect.return_value = mail_send.SmtpSendResult(
            conn=mock_conn, sender_email="sender@yandex.ru"
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

    # Verify send_message was called
    mock_conn.send_message.assert_called_once()
    msg = mock_conn.send_message.call_args[0][0]
    assert msg["To"] == "recipient@example.com"
    assert msg["Subject"] == "Test Subject"
    assert msg["From"] == "sender@yandex.ru"


@patch("send_email.smtplib.SMTP_SSL")
def test_send_with_cc_and_bcc(mock_smtp_cls: MagicMock) -> None:
    mock_conn = MagicMock()
    mock_conn.docmd.return_value = (235, b"OK")
    mock_smtp_cls.return_value = mock_conn

    sender = build_sender()

    with patch.object(sender, "_connect_smtp") as mock_connect:
        mock_connect.return_value = mail_send.SmtpSendResult(
            conn=mock_conn, sender_email="s@yandex.ru"
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

    msg = mock_conn.send_message.call_args[0][0]
    # BCC must NOT appear in message headers
    assert "secret@example.com" not in (msg.get("To", "") + msg.get("Cc", ""))


@patch("send_email.smtplib.SMTP_SSL")
def test_send_html_content_type(mock_smtp_cls: MagicMock) -> None:
    mock_conn = MagicMock()
    mock_smtp_cls.return_value = mock_conn

    sender = build_sender()

    with patch.object(sender, "_connect_smtp") as mock_connect:
        mock_connect.return_value = mail_send.SmtpSendResult(
            conn=mock_conn, sender_email="s@y.ru"
        )
        sender.send(
            to="a@b.com",
            subject="HTML",
            body="<h1>Hello</h1>",
            content_type="html",
        )

    msg = mock_conn.send_message.call_args[0][0]
    assert "text/html" in msg.get_content_type()


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
        # Patch __init__ to avoid load_runtime_context
        with patch.object(mail_send.EmailSender, "__init__", lambda self, **kw: None):
            ret = mail_send.main([
                "--to", "a@b.com",
                "--subject", "Test",
                "--body-file", str(body_file),
            ])

    assert ret == 0
    call_kwargs = mock_send.call_args[1]
    assert call_kwargs["body"] == "File body content"


def test_cli_json_output() -> None:
    with patch.object(mail_send.EmailSender, "send") as mock_send:
        mock_send.return_value = {
            "status": "sent",
            "from": "s@y.ru",
            "to": ["a@b.com"],
            "subject": "Test",
            "message_id": "123",
        }
        with patch.object(mail_send.EmailSender, "__init__", lambda self, **kw: None):
            ret = mail_send.main([
                "--to", "a@b.com",
                "--subject", "Test",
                "--body", "Hello",
                "--format", "json",
            ])

    assert ret == 0
