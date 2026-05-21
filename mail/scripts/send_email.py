#!/usr/bin/env python3
"""
Yandex Mail sender via SMTP XOAUTH2.

Connects to Yandex Mail SMTP, authenticates with OAuth2 (XOAUTH2 SASL),
and sends emails from token-backed Yandex accounts.

Designed to follow the same patterns as fetch_emails.py:
- Uses ``@yandex_api_method`` decorator for auth dispatch.
- Loads config via ``load_runtime_context``.
- Provides a CLI with argparse.

Usage examples:

    # Send a simple email
    python3 send_email.py --account alex --to user@example.com --subject "Hello" --body "Hi there"

    # Send with CC and Reply-To
    python3 send_email.py --account alex --to user@example.com --cc other@example.com \
        --reply-to sender@example.com --subject "Re: Topic" --body "Reply body"

    # Read body from file
    python3 send_email.py --account alex --to user@example.com --subject "Report" \
        --body-file /path/to/report.txt

    # JSON output
    python3 send_email.py --account alex --to user@example.com --subject "Test" --body "OK" --format json
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.api import YandexApiContext, yandex_api_method
from common.config import load_runtime_context

logger = logging.getLogger("mail.send")


class SmtpSendResult:
    """Holds the SMTP connection and the resolved sender email after auth."""

    __slots__ = ("conn", "sender_email")

    def __init__(self, conn: smtplib.SMTP_SSL, sender_email: str) -> None:
        self.conn = conn
        self.sender_email = sender_email


class EmailSender:
    """Send Yandex Mail messages for token-backed Yandex accounts."""

    def __init__(
        self,
        *,
        data_dir: str | None = None,
    ):
        """Initialize sender from shared + agent config."""
        self.runtime = load_runtime_context(
            __file__,
            data_dir_override=data_dir,
            require_agent_config=True,
            require_external_data_dir=True,
        )
        self.config = self.runtime.config
        self.data_dir = self.runtime.data_dir

    def _api_context(self, account: str | None = None) -> YandexApiContext:
        """Build a fresh API context for the auth dispatcher."""
        import requests

        return YandexApiContext(
            account=account,
            data_dir=self.data_dir,
            config=self.config,
            session=requests.Session(),
        )

    @staticmethod
    def _mail_credentials(ctx: YandexApiContext) -> tuple[str, str]:
        """Resolve verified email and bearer token from the API context."""
        if ctx.token_ref is None:
            raise RuntimeError("Mail API context is not token-bound")
        email_addr = str((ctx.token_data or {}).get("email") or "").strip()
        if not email_addr:
            raise RuntimeError("Mail token file is missing verified email")
        return email_addr, ctx.token_ref.token

    @yandex_api_method("mail.smtp.send", one_of=["mail:imap_full", "mail:imap_ro"])
    def _connect_smtp(self, ctx: YandexApiContext) -> SmtpSendResult:
        """Authenticate to SMTP with the shared auth dispatcher token."""
        smtp_cfg = self.config.get("smtp", {})
        server = smtp_cfg.get("server", "smtp.yandex.com")
        port = int(smtp_cfg.get("port", 465))

        email_addr, token = self._mail_credentials(ctx)
        auth_string = f"user={email_addr}\x01auth=Bearer {token}\x01\x01"
        context = ssl.create_default_context()
        conn = smtplib.SMTP_SSL(server, port, context=context, timeout=30)
        conn.ehlo()
        code, message = conn.docmd(
            "AUTH", "XOAUTH2 " + base64.b64encode(auth_string.encode()).decode()
        )
        if code != 235:
            conn.quit()
            raise RuntimeError(
                f"SMTP XOAUTH2 auth failed: {code} {message.decode(errors='replace')}"
            )
        return SmtpSendResult(conn=conn, sender_email=email_addr)

    def send(
        self,
        *,
        to: str | list[str],
        subject: str,
        body: str,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        reply_to: str | None = None,
        content_type: str = "plain",
        account: str | None = None,
    ) -> dict[str, Any]:
        """Send an email and return a result dict.

        Parameters
        ----------
        to : str or list[str]
            Recipient email address(es).
        subject : str
            Email subject line.
        body : str
            Email body text.
        cc : str or list[str], optional
            CC recipient(s).
        bcc : str or list[str], optional
            BCC recipient(s).
        reply_to : str, optional
            Reply-To header value.
        content_type : str
            "plain" (default) or "html".
        account : str, optional
            Account alias to use.

        Returns
        -------
        dict
            ``{"status": "sent", "from": ..., "to": [...], "message_id": ...}``
        """
        ctx = self._api_context(account=account)
        result = self._connect_smtp(ctx=ctx)
        conn = result.conn
        sender_email = result.sender_email

        try:
            msg = EmailMessage()
            msg["From"] = sender_email

            to_list = [to] if isinstance(to, str) else to
            msg["To"] = ", ".join(to_list)

            cc_list: list[str] = []
            if cc:
                cc_list = [cc] if isinstance(cc, str) else cc
                msg["Cc"] = ", ".join(cc_list)

            if reply_to:
                msg["Reply-To"] = reply_to

            msg["Subject"] = subject

            if content_type == "html":
                msg.set_content(body, subtype="html")
            else:
                msg.set_content(body)

            # Build full recipient list for SMTP envelope (includes BCC)
            all_recipients = list(to_list)
            if cc_list:
                all_recipients.extend(cc_list)
            if bcc:
                bcc_list = [bcc] if isinstance(bcc, str) else bcc
                all_recipients.extend(bcc_list)

            conn.send_message(msg)
            message_id = msg.get("Message-ID", "")

            send_result: dict[str, Any] = {
                "status": "sent",
                "from": sender_email,
                "to": to_list,
                "subject": subject,
                "message_id": message_id,
            }
            if cc:
                send_result["cc"] = [cc] if isinstance(cc, str) else cc
            if bcc:
                send_result["bcc"] = [bcc] if isinstance(bcc, str) else bcc
            if reply_to:
                send_result["reply_to"] = reply_to

            return send_result
        finally:
            try:
                conn.quit()
            except Exception:
                pass


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Send email via Yandex Mail SMTP with OAuth2",
    )
    parser.add_argument(
        "--account",
        help="Account alias to use for sending",
    )
    parser.add_argument(
        "--to",
        required=True,
        nargs="+",
        help="Recipient email address(es)",
    )
    parser.add_argument(
        "--subject",
        required=True,
        help="Email subject",
    )
    parser.add_argument(
        "--body",
        help="Email body text",
    )
    parser.add_argument(
        "--body-file",
        help="Read body from file (useful for multi-line content)",
    )
    parser.add_argument(
        "--cc",
        nargs="+",
        help="CC recipient(s)",
    )
    parser.add_argument(
        "--bcc",
        nargs="+",
        help="BCC recipient(s)",
    )
    parser.add_argument(
        "--reply-to",
        help="Reply-To header",
    )
    parser.add_argument(
        "--content-type",
        choices=["plain", "html"],
        default="plain",
        help="Body content type (default: plain)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        dest="output_format",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--data-dir",
        help="Override data directory path",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.body and not args.body_file:
        print("Error: --body or --body-file is required", file=sys.stderr)
        return 1

    body = args.body or ""
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")

    sender = EmailSender(data_dir=args.data_dir)
    result = sender.send(
        to=args.to,
        subject=args.subject,
        body=body,
        cc=args.cc,
        bcc=args.bcc,
        reply_to=args.reply_to,
        content_type=args.content_type,
        account=args.account,
    )

    if args.output_format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Sent: {result['from']} -> {', '.join(result['to'])}")
        print(f"Subject: {result['subject']}")
        print(f"Message-ID: {result.get('message_id', 'N/A')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
