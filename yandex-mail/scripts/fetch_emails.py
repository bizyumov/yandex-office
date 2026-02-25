#!/usr/bin/env python3
"""
Yandex Mail fetcher via IMAP XOAUTH2.

Connects to Yandex Mail, fetches emails from configured senders, downloads
attachments and email body into structured `incoming/` directories.

Designed to be run as a cron job. State is persisted after each email
to prevent data loss on interruption.

Output structure per email:
    {data_dir}/incoming/{YYYY-MM-DD}_{mailbox}_uid{N}/
        {original_attachment_filename}   # Preserved original name
        email_body.txt                   # HTML→text converted body
        email_body.html                  # Raw HTML body (if available)
        meta.json                        # Metadata (no business logic)
"""

import imaplib
import ssl
import json
import email
import email.utils
import re
import logging
import time
from pathlib import Path
from email.header import decode_header
from datetime import datetime, timezone


logger = logging.getLogger("yandex-mail")


def _find_config() -> Path:
    """Walk up from script to find config.json at yandex-skills/ root."""
    p = Path(__file__).resolve().parent
    for _ in range(5):
        candidate = p / "config.json"
        if candidate.exists():
            return candidate
        p = p.parent
    raise FileNotFoundError("config.json not found in parent directories")


def _resolve_data_dir(config: dict, config_path: Path) -> Path:
    """Resolve data_dir from config, relative to config file location."""
    data_dir = config.get("data_dir", "data")
    return (config_path.parent / data_dir).resolve()


class EmailFetcher:
    def __init__(self, config_path: str | Path | None = None):
        """Initialize fetcher with shared config.

        If config_path is None, auto-discovers config.json from parent dirs.
        """
        if config_path is None:
            self.config_path = _find_config()
        else:
            self.config_path = Path(config_path)

        self.config = self._load_config()
        self.data_dir = _resolve_data_dir(self.config, self.config_path)
        self.state = self._load_state()
        self.downloaded = []

    def _load_config(self) -> dict:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config not found: {self.config_path}")
        return json.loads(self.config_path.read_text())

    def _load_state(self) -> dict:
        state_file = self.config.get("mail", {}).get("state_file", "state.json")
        state_path = self.data_dir / state_file
        if state_path.exists():
            return json.loads(state_path.read_text())
        return {"mailboxes": {}}

    def _save_state(self):
        state_file = self.config.get("mail", {}).get("state_file", "state.json")
        state_path = self.data_dir / state_file
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = state_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(self.state, indent=2))
        tmp_path.replace(state_path)

    def _get_last_uid(self, mailbox_name: str) -> int:
        return self.state["mailboxes"].get(mailbox_name, {}).get("last_uid", 0)

    def _update_last_uid(self, mailbox_name: str, uid: int):
        if mailbox_name not in self.state["mailboxes"]:
            self.state["mailboxes"][mailbox_name] = {}
        self.state["mailboxes"][mailbox_name]["last_uid"] = uid
        self.state["mailboxes"][mailbox_name]["last_check"] = datetime.now().isoformat()

    def _connect_imap(self, email_addr: str, token: str) -> imaplib.IMAP4_SSL:
        imap_cfg = self.config.get("imap", {})
        server = imap_cfg.get("server", "imap.yandex.com")
        port = imap_cfg.get("port", 993)

        auth_string = f"user={email_addr}\x01auth=Bearer {token}\x01\x01"
        context = ssl.create_default_context()
        conn = imaplib.IMAP4_SSL(server, port, ssl_context=context)
        conn.authenticate("XOAUTH2", lambda x: auth_string.encode())
        conn.select("INBOX")
        return conn

    @staticmethod
    def _decode_header(header_value: str) -> str:
        if not header_value:
            return ""
        decoded_parts = decode_header(header_value)
        result = []
        for content, encoding in decoded_parts:
            if isinstance(content, bytes):
                content = content.decode(encoding or "utf-8", errors="replace")
            result.append(content)
        return " ".join(result)

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Extract visible text from HTML email body."""
        import html as html_mod
        text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<br\s*/?\s*>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</(p|div|tr|li|h[1-6])>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        text = html_mod.unescape(text)
        lines = [line.strip() for line in text.splitlines()]
        lines = [l for l in lines if l]
        return '\n'.join(lines)

    def _search_emails(self, conn, sender: str, last_uid: int) -> list[tuple[int, bytes]]:
        """Search for new emails from sender after last_uid.

        Returns ALL matching UIDs — no subject filtering.
        Note: Yandex IMAP doesn't support combining FROM + UID criteria
        in a single SEARCH, so we search by FROM and filter UID in Python.
        """
        _, uid_data = conn.uid("SEARCH", None, f'FROM "{sender}"')
        if not uid_data[0]:
            return []

        result = []
        for uid_bytes in uid_data[0].split():
            uid = int(uid_bytes)
            if uid <= last_uid:
                continue
            result.append((uid, uid_bytes))

        return sorted(result, key=lambda x: x[0])

    def _process_email(self, conn, uid_bytes: bytes, uid: int, mailbox_name: str) -> dict | None:
        """Fetch a single email and write to incoming/ directory.

        Saves email body (text + HTML), attachments, and generic metadata.
        No business logic — downstream skills enrich meta.json as needed.
        """
        _, msg_data = conn.uid("FETCH", uid_bytes, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = self._decode_header(msg.get("Subject", ""))
        date_str = msg.get("Date", "")
        sender_raw = msg.get("From", "")
        sender = self._decode_header(sender_raw)

        # Parse date to UTC ISO 8601 timestamp
        try:
            date_parsed = email.utils.parsedate_to_datetime(date_str)
            timestamp = date_parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            date_formatted = date_parsed.strftime("%Y-%m-%d")
        except Exception:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            date_formatted = datetime.now().strftime("%Y-%m-%d")

        # Extract email body (prefer text/plain, fallback to text/html)
        email_body_text = None
        email_body_html = None
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get("Content-Disposition") is not None:
                continue
            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            if part.get_content_type() == "text/plain" and email_body_text is None:
                email_body_text = payload.decode(charset, errors="replace")
            elif part.get_content_type() == "text/html" and email_body_html is None:
                email_body_html = payload.decode(charset, errors="replace")

        body_for_text = email_body_text or (
            self._html_to_text(email_body_html) if email_body_html else ""
        )

        # Create incoming directory
        incoming_dir = self.data_dir / "incoming"
        dir_name = f"{date_formatted}_{mailbox_name}_uid{uid}"
        email_dir = incoming_dir / dir_name
        email_dir.mkdir(parents=True, exist_ok=True)

        # Save email body (text)
        if body_for_text:
            (email_dir / "email_body.txt").write_text(body_for_text, encoding="utf-8")

        # Save email body (HTML) for downstream skill parsing
        if email_body_html:
            (email_dir / "email_body.html").write_text(email_body_html, encoding="utf-8")

        # Download attachments (preserve original filenames)
        attachment_files = []
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get("Content-Disposition") is None:
                continue
            filename = part.get_filename()
            if not filename:
                continue
            filename = self._decode_header(filename)
            filepath = email_dir / filename
            filepath.write_bytes(part.get_payload(decode=True))
            attachment_files.append(filename)

        # Build metadata — generic, no business logic
        meta = {
            "imap_uid": uid,
            "mailbox": mailbox_name,
            "subject": subject,
            "sender": sender,
            "timestamp": timestamp,
            "attachments": attachment_files,
            "dir_name": dir_name,
        }

        # Save metadata
        (email_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        return meta

    def fetch_mailbox(self, mailbox_config: dict, max_messages: int | None = None) -> int:
        """Fetch emails from a single mailbox.

        Args:
            mailbox_config: Mailbox config entry with name/email.
            max_messages: Optional cap for this mailbox in current run.

        Returns:
            Number of successfully fetched messages.
        """
        mailbox_name = mailbox_config["name"]
        email_addr = mailbox_config["email"]

        logger.info(f"Checking mailbox: {email_addr} ({mailbox_name})")

        # Load token from data_dir/auth/{name}.token
        token_path = self.data_dir / "auth" / f"{mailbox_name}.token"
        if not token_path.exists():
            logger.error(f"Token not found: {token_path}")
            return 0

        token_data = json.loads(token_path.read_text())
        token = token_data.get("token.mail")
        if not token:
            logger.error(f"No 'token.mail' found in {token_path}")
            return 0

        # Connect with retry
        conn = None
        for attempt in range(3):
            try:
                conn = self._connect_imap(email_addr, token)
                logger.info("Connected to IMAP")
                break
            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
        if conn is None:
            logger.error("All connection attempts failed")
            return 0

        last_uid = self._get_last_uid(mailbox_name)
        logger.info(f"Last processed UID: {last_uid}")

        # Search for emails matching filter
        sender = self.config.get("mail", {}).get("filters", {}).get("sender", "")
        if not sender:
            logger.error("No mail.filters.sender configured")
            conn.logout()
            return 0

        try:
            matching = self._search_emails(conn, sender, last_uid)
        except Exception as e:
            logger.error(f"Search failed: {e}")
            conn.logout()
            return 0

        if max_messages is not None:
            matching = matching[:max_messages]
            logger.info(f"Found {len(matching)} new emails (capped by --num)")
        else:
            logger.info(f"Found {len(matching)} new emails")

        fetched_count = 0

        # Process each email
        for uid, uid_bytes in matching:
            logger.info(f"Processing UID {uid}...")
            try:
                meta = self._process_email(conn, uid_bytes, uid, mailbox_name)
                if meta:
                    self.downloaded.append(meta)
                    self._update_last_uid(mailbox_name, uid)
                    self._save_state()
                    fetched_count += 1
                    logger.info(
                        f"  OK: {meta['subject'][:50]} "
                        f"attachments={len(meta['attachments'])}"
                    )
            except Exception as e:
                logger.error(f"  Failed UID {uid}: {e}")

        conn.logout()
        logger.info("Disconnected")
        return fetched_count

    def fetch_all(self, num_messages: int | None = None) -> list[dict]:
        """Fetch from all configured mailboxes.

        Args:
            num_messages: Optional global cap for fetched messages in this run.
        """
        remaining = num_messages

        for mailbox_config in self.config["mailboxes"]:
            if remaining is not None and remaining <= 0:
                logger.info("Reached --num cap; stopping mailbox scan")
                break

            fetched = self.fetch_mailbox(mailbox_config, max_messages=remaining)
            if remaining is not None:
                remaining -= fetched

        return self.downloaded


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Fetch emails from Yandex Mail")
    parser.add_argument(
        "--config", "-c", default=None, help="Path to config.json (auto-discovers if omitted)"
    )
    parser.add_argument(
        "--num",
        type=int,
        default=None,
        help="Maximum number of new messages to fetch in this run (global cap across mailboxes)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )
    args = parser.parse_args()

    if args.num is not None and args.num <= 0:
        parser.error("--num must be a positive integer")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    fetcher = EmailFetcher(args.config)
    results = fetcher.fetch_all(num_messages=args.num)

    print(json.dumps({
        "fetched": len(results),
        "emails": [
            {
                "uid": r["imap_uid"],
                "subject": r["subject"],
                "attachments": len(r["attachments"]),
            }
            for r in results
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
