#!/usr/bin/env python3
"""
Yandex Mail sender via SMTP XOAUTH2 and managed auth.

Designed to follow the same patterns as fetch_emails.py:
- Uses ``@yandex_api_method`` decorator for OAuth2 auth dispatch.
- Loads config via ``load_runtime_context``.
- Provides a CLI with argparse.

Usage examples:

    # Send a simple email
    python3 send_email.py --account alex --to user@example.com --subject "Hello" --body "Hi there"

    # Send with CC and Reply-To
    python3 send_email.py --to user@example.com --cc other@example.com \\
        --reply-to sender@example.com --subject "Re: Topic" --body "Reply body"

    # Read body from file
    python3 send_email.py --to user@example.com --subject "Report" \\
        --body-file /path/to/report.txt

    # JSON output
    python3 send_email.py --to user@example.com --subject "Test" --body "OK" --format json
"""

from __future__ import annotations

import argparse
import base64
import json
import imaplib
import mimetypes
import re
import time
from email import policy
from email.parser import BytesParser
from email.utils import make_msgid, formatdate
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

# ---------------------------------------------------------------------------
# SMTP connection builders
# ---------------------------------------------------------------------------

class SmtpSendResult:
    """Holds the SMTP connection and the resolved sender email after auth."""

    __slots__ = ("conn", "sender_email")

    def __init__(self, conn: smtplib.SMTP_SSL, sender_email: str) -> None:
        self.conn = conn
        self.sender_email = sender_email


class EmailSender:
    """Send Yandex Mail messages with managed OAuth2 SMTP auth."""

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
        """Build a fresh API context for the OAuth2 auth dispatcher."""
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

    @yandex_api_method("mail.smtp.send", one_of=["mail:smtp"])
    def _connect_smtp_oauth2(self, ctx: YandexApiContext) -> SmtpSendResult:
        """Authenticate to SMTP with XOAUTH2 using the selected managed token."""
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
        logger.info("SMTP XOAUTH2 auth succeeded for %s", email_addr)
        return SmtpSendResult(conn=conn, sender_email=email_addr)

    def _connect_smtp(self, *, account: str | None = None) -> SmtpSendResult:
        """Authenticate through the managed OAuth2 decorator path."""
        ctx = self._api_context(account=account)
        return self._connect_smtp_oauth2(ctx=ctx)

    @yandex_api_method("mail.imap.sent_copy", one_of=["mail:imap_full"])
    def _connect_sent_oauth2(self, ctx: YandexApiContext) -> tuple[Any, str]:
        """Full-access managed auth, separate from SMTP and readonly fetch scopes."""
        cfg = self.config.get("imap", {})
        email_addr, token = self._mail_credentials(ctx)
        conn = imaplib.IMAP4_SSL(
            cfg.get("server", "imap.yandex.com"), int(cfg.get("port", 993)),
            ssl_context=ssl.create_default_context(), timeout=30,
        )
        try:
            auth = f"user={email_addr}\x01auth=Bearer {token}\x01\x01".encode()
            conn.authenticate("XOAUTH2", lambda _: auth)
            return conn, email_addr
        except Exception:
            self._close(conn, "logout")
            raise

    def _connect_sent(self, *, account: str | None = None) -> tuple[Any, str]:
        return self._connect_sent_oauth2(ctx=self._api_context(account=account))

    @staticmethod
    def _close(conn: Any, method: str) -> None:
        if conn is not None:
            try:
                getattr(conn, method)()
            except Exception:
                pass

    @staticmethod
    def _message_signature(raw: bytes) -> tuple:
        """Ignore transport-added headers but verify all composed content."""
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        headers = tuple((name, tuple(str(v) for v in msg.get_all(name, []))) for name in
                        ("Message-ID", "Date", "From", "To", "Cc", "Bcc", "Subject", "Reply-To"))
        parts = tuple((p.get_content_type(), p.get_content_disposition(), p.get_filename(),
                       p.get_content_charset(), p.get_payload(decode=True))
                      for p in msg.walk() if not p.is_multipart())
        return headers, parts

    def _save_sent(self, conn: Any, raw: bytes) -> dict[str, Any]:
        copy: dict[str, Any] = {"status": "failed", "folder": "Sent"}
        try:
            typ, data = conn.append("Sent", "\\Seen", imaplib.Time2Internaldate(time.time()), raw)
            if typ != "OK":
                return {**copy, "error": "append_rejected"}
            copy["status"] = "unverified"
            match = re.search(rb"APPENDUID (\d+) (\d+)\]", b" ".join(x for x in data if isinstance(x, bytes)))
            if not match:
                return {**copy, "error": "append_uid_missing"}
            copy["uid"] = match.group(2).decode("ascii")
            typ, _ = conn.select("Sent", readonly=True)
            if typ != "OK":
                return {**copy, "error": "sent_select_failed"}
            typ, data = conn.uid("fetch", copy["uid"], "(BODY.PEEK[])")
            bodies = [x[1] for x in data if isinstance(x, tuple) and isinstance(x[1], bytes)]
            if typ != "OK" or len(bodies) != 1:
                return {**copy, "error": "sent_fetch_failed"}
            if self._message_signature(bodies[0]) != self._message_signature(raw):
                return {**copy, "error": "sent_content_mismatch"}
            copy["status"] = "verified"
            return copy
        except Exception:
            # APPEND can succeed server-side before a disconnect: never retry blindly.
            return {**copy, "error": "sent_copy_exception", "retry_safe": False}

    def send(
        self, *, to: str | list[str], subject: str, body: str,
        cc: str | list[str] | None = None, bcc: str | list[str] | None = None,
        reply_to: str | None = None, content_type: str = "plain",
        account: str | None = None, attachments: list[str | Path] | None = None,
        save_sent: bool = False,
    ) -> dict[str, Any]:
        """Send once; optionally archive and verify without ever retrying SMTP.

        Attachments are local files read before authentication. ``save_sent`` is
        opt-in and requires full IMAP access for the same SMTP identity. Result
        ``smtp_status`` and ``sent_copy.status`` describe independent outcomes.
        Post-send failures return structured partial results, not retry signals.
        """
        if content_type not in ("plain", "html"):
            raise ValueError("content_type must be plain or html")
        to_list = [to] if isinstance(to, str) else list(to)
        cc_list = [cc] if isinstance(cc, str) else list(cc or [])
        bcc_list = [bcc] if isinstance(bcc, str) else list(bcc or [])
        if not to_list or any(not a.strip() for a in to_list + cc_list + bcc_list):
            raise ValueError("Nonempty recipients are required")
        msg = EmailMessage(policy=policy.SMTP)
        msg["To"] = ", ".join(to_list)
        msg["Subject"] = subject
        msg["Message-ID"] = make_msgid()
        msg["Date"] = formatdate(localtime=False)
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.set_content(body, subtype=content_type)
        for filename in attachments or []:
            path = Path(filename)
            payload = path.read_bytes()  # raises before any network activity
            mime, encoding = mimetypes.guess_type(path.name)
            maintype, subtype = (mime if mime and not encoding else "application/octet-stream").split("/", 1)
            msg.add_attachment(payload, maintype=maintype, subtype=subtype, filename=path.name)
        smtp = None
        imap = None
        try:
            connection = self._connect_smtp(account=account)
            smtp = connection.conn
            sender_email = connection.sender_email
            msg["From"] = sender_email
            raw = msg.as_bytes()  # freeze MIME boundaries, identifiers and bytes once
            if save_sent:
                imap, imap_email = self._connect_sent(account=account)
                if imap_email.casefold() != sender_email.casefold():
                    raise RuntimeError("SMTP and IMAP identities do not match")
                typ, _ = imap.select("Sent", readonly=True)
                if typ != "OK":
                    raise RuntimeError("Sent folder preflight failed; email not sent")
            result: dict[str, Any] = {
                "status": "sent", "from": sender_email, "to": to_list,
                "subject": subject, "message_id": str(msg["Message-ID"]),
                "smtp_status": "accepted", "retry_safe": False,
                "sent_copy": {"status": "not_attempted" if save_sent else "not_requested"},
            }
            for key, value in (("cc", cc_list), ("bcc", bcc_list), ("reply_to", reply_to)):
                if value:
                    result[key] = value
            try:
                refused = smtp.sendmail(sender_email, to_list + cc_list + bcc_list, raw)
            except smtplib.SMTPRecipientsRefused:
                result.update(status="failed", smtp_status="refused")
                return result
            except smtplib.SMTPResponseException:
                result.update(status="failed", smtp_status="refused")
                return result
            except Exception:
                result.update(status="partial", smtp_status="unknown", error="smtp_outcome_unknown")
                return result
            if refused:
                result.update(status="partial", smtp_status="partial", refused_recipients=list(refused))
            if save_sent:
                result["sent_copy"] = self._save_sent(imap, raw)
                if result["sent_copy"]["status"] != "verified":
                    result["status"] = "partial"
            return result
        finally:
            self._close(smtp, "quit")
            self._close(imap, "logout")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Send email via Yandex Mail SMTP XOAUTH2",
    )
    parser.add_argument(
        "--account",
        help="Managed account alias to use",
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
    parser.add_argument("--attachment", action="append", default=[], help="Local file to attach (repeatable)")
    parser.add_argument("--save-sent", action="store_true", help="Save and verify a Sent copy using full IMAP access")
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
        attachments=args.attachment,
        save_sent=args.save_sent,
    )

    if args.output_format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Status: {result['status']}; SMTP: {result.get('smtp_status', 'accepted')}")
        print(f"Sent copy: {result.get('sent_copy', {})}")
        print(f"From: {result['from']} -> {', '.join(result['to'])}")
        print(f"Subject: {result['subject']}")
        print(f"Message-ID: {result.get('message_id', 'N/A')}")

    return 0 if result["status"] == "sent" else 2


if __name__ == "__main__":
    raise SystemExit(main())
