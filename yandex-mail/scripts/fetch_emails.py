#!/usr/bin/env python3
"""
Yandex Mail fetcher via IMAP XOAUTH2.

Connects to Yandex Mail, fetches emails from configured senders, downloads
attachments and email body into structured `incoming/` directories.

Designed to be run as a cron job. State is persisted after each email
to prevent data loss on interruption.

Output structure per email:
    incoming/{YYYY-MM-DD}_{mailbox}_uid{N}/
        {original_attachment_filename}   # Preserved original name
        email_body.txt                   # HTML→text converted body
        meta.json                        # Enriched metadata
"""

import imaplib
import ssl
import json
import email
import email.utils
import os
import re
import logging
import time
from pathlib import Path
from email.header import decode_header
from datetime import datetime

logger = logging.getLogger("yandex-mail")

# Telemost meeting UID pattern in email body
TELEMOST_UID_RE = re.compile(r'https://telemost\.yandex\.ru/j/(\d+)')

# Meeting title in "Запись встречи «Title» от DD.MM.YYYY"
MEETING_TITLE_RE = re.compile(r'\u00ab(.+?)\u00bb')

# yadi.sk links for video/audio
YADISK_LINK_RE = re.compile(r'https://yadi\.sk/[a-zA-Z0-9/_-]+')


class EmailFetcher:
    def __init__(self, config_path: str | Path):
        """Initialize fetcher with config."""
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.state = self._load_state()
        self.downloaded = []

    def _load_config(self) -> dict:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config not found: {self.config_path}")
        return json.loads(self.config_path.read_text())

    def _load_state(self) -> dict:
        state_path = self.config_path.parent / self.config["state_file"]
        if state_path.exists():
            return json.loads(state_path.read_text())
        return {"mailboxes": {}}

    def _save_state(self):
        state_path = self.config_path.parent / self.config["state_file"]
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
        auth_string = f"user={email_addr}\x01auth=Bearer {token}\x01\x01"
        context = ssl.create_default_context()
        conn = imaplib.IMAP4_SSL(
            self.config["imap_server"],
            self.config["imap_port"],
            ssl_context=context,
        )
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
        return "".join(result)

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

    @staticmethod
    def classify_email(subject: str) -> str:
        """Classify email type from subject line.

        Returns: 'konspekt', 'zapis', or 'unknown'
        """
        if subject.startswith("Конспект встречи"):
            return "konspekt"
        if subject.startswith("Запись встречи"):
            return "zapis"
        return "unknown"

    @staticmethod
    def extract_meeting_uid(html_body: str) -> str | None:
        """Extract Telemost meeting UID from email HTML body.

        Looks for https://telemost.yandex.ru/j/{UID} pattern.
        """
        match = TELEMOST_UID_RE.search(html_body)
        return match.group(1) if match else None

    @staticmethod
    def extract_meeting_title(subject: str) -> str | None:
        """Extract meeting title from 'Запись встречи «Title» от ...' subject."""
        match = MEETING_TITLE_RE.search(subject)
        return match.group(1) if match else None

    @staticmethod
    def extract_media_links(html_body: str) -> list[str]:
        """Extract yadi.sk links from email body."""
        return YADISK_LINK_RE.findall(html_body)

    def _search_emails(self, conn, sender: str, last_uid: int) -> list[tuple[int, bytes]]:
        """Search for new emails from sender after last_uid.

        Uses UID SEARCH for efficiency. Accepts both "Конспект встречи"
        and "Запись встречи" subjects.
        """
        # UID SEARCH returns UIDs directly — much faster than N+1 fetches
        criteria = f'FROM "{sender}" UID {last_uid + 1}:*'
        _, uid_data = conn.uid("SEARCH", None, criteria)
        if not uid_data[0]:
            return []

        matching_uids = []
        for uid_bytes in uid_data[0].split():
            uid = int(uid_bytes)
            if uid <= last_uid:
                continue

            # Fetch subject header to classify
            _, msg_data = conn.uid(
                "FETCH", uid_bytes, "(BODY[HEADER.FIELDS (SUBJECT)])"
            )
            subject_raw = msg_data[0][1].decode("utf-8", errors="replace")
            subject = self._decode_header(
                subject_raw.replace("Subject: ", "").strip()
            )

            email_type = self.classify_email(subject)
            if email_type != "unknown":
                matching_uids.append((uid, uid_bytes))

        return sorted(matching_uids, key=lambda x: x[0])

    def _process_email(self, conn, uid_bytes: bytes, uid: int, mailbox_name: str) -> dict | None:
        """Fetch a single email and write to incoming/ directory.

        Returns metadata dict or None on failure.
        """
        _, msg_data = conn.uid("FETCH", uid_bytes, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = self._decode_header(msg.get("Subject", ""))
        date_str = msg.get("Date", "")
        sender = msg.get("From", "")

        try:
            date_parsed = email.utils.parsedate_to_datetime(date_str)
            date_formatted = date_parsed.strftime("%Y-%m-%d")
        except Exception:
            date_formatted = datetime.now().strftime("%Y-%m-%d")

        # Classify
        email_type = self.classify_email(subject)

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

        # Keep raw HTML for UID/link extraction, convert for text output
        body_for_text = email_body_text or (
            self._html_to_text(email_body_html) if email_body_html else ""
        )
        body_for_parsing = email_body_html or ""

        # Extract meeting UID from HTML body
        meeting_uid = self.extract_meeting_uid(body_for_parsing)

        # Extract meeting title (only from "Запись" subjects)
        meeting_title = None
        if email_type == "zapis":
            meeting_title = self.extract_meeting_title(subject)

        # Extract yadi.sk media links
        media_links = self.extract_media_links(body_for_parsing)

        # Create incoming directory
        incoming_dir = Path(self.config.get("incoming_dir", "incoming"))
        dir_name = f"{date_formatted}_{mailbox_name}_uid{uid}"
        email_dir = incoming_dir / dir_name
        email_dir.mkdir(parents=True, exist_ok=True)

        # Save email body
        if body_for_text:
            (email_dir / "email_body.txt").write_text(body_for_text, encoding="utf-8")

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

        # Build metadata
        meta = {
            "imap_uid": uid,
            "mailbox": mailbox_name,
            "subject": subject,
            "sender": sender,
            "date": date_formatted,
            "email_type": email_type,
            "meeting_uid": meeting_uid,
            "meeting_title": meeting_title,
            "media_links": media_links,
            "attachments": attachment_files,
            "dir_name": dir_name,
        }

        # Save metadata
        (email_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        return meta

    def fetch_mailbox(self, mailbox_config: dict):
        """Fetch emails from a single mailbox."""
        mailbox_name = mailbox_config["name"]
        email_addr = mailbox_config["email"]

        logger.info(f"Checking mailbox: {email_addr} ({mailbox_name})")

        # Load token
        token_path = self.config_path.parent / mailbox_config["token_file"]
        if not token_path.exists():
            logger.error(f"Token not found: {token_path}")
            return

        token_data = json.loads(token_path.read_text())
        token = token_data["token"]

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
            return

        last_uid = self._get_last_uid(mailbox_name)
        logger.info(f"Last processed UID: {last_uid}")

        # Search (accepts both "Конспект" and "Запись")
        sender = self.config["filters"]["sender"]
        try:
            matching = self._search_emails(conn, sender, last_uid)
            logger.info(f"Found {len(matching)} new emails")
        except Exception as e:
            logger.error(f"Search failed: {e}")
            conn.logout()
            return

        # Process each email
        for uid, uid_bytes in matching:
            logger.info(f"Processing UID {uid}...")
            try:
                meta = self._process_email(conn, uid_bytes, uid, mailbox_name)
                if meta:
                    self.downloaded.append(meta)
                    # Save state after each successful email (Option A)
                    self._update_last_uid(mailbox_name, uid)
                    self._save_state()
                    logger.info(
                        f"  OK: {meta['email_type']} "
                        f"meeting_uid={meta['meeting_uid']} "
                        f"attachments={len(meta['attachments'])}"
                    )
            except Exception as e:
                logger.error(f"  Failed UID {uid}: {e}")
                # Do NOT advance UID — will retry on next run

        conn.logout()
        logger.info("Disconnected")

    def fetch_all(self) -> list[dict]:
        """Fetch from all configured mailboxes."""
        for mailbox_config in self.config["mailboxes"]:
            self.fetch_mailbox(mailbox_config)
        return self.downloaded


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Fetch emails from Yandex Mail")
    parser.add_argument(
        "--config", "-c", default="config.json", help="Path to config.json"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    fetcher = EmailFetcher(args.config)
    results = fetcher.fetch_all()

    # Summary
    print(json.dumps({
        "fetched": len(results),
        "emails": [
            {
                "uid": r["imap_uid"],
                "type": r["email_type"],
                "meeting_uid": r["meeting_uid"],
                "attachments": len(r["attachments"]),
            }
            for r in results
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
