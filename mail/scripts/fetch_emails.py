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

from __future__ import annotations

import argparse
import email
import email.utils
import imaplib
import json
import logging
import re
import ssl
import sys
import time
from datetime import datetime, timezone
from email.header import decode_header
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.auth import resolve_token
from common.config import load_runtime_context

logger = logging.getLogger("mail")


class EmailFetcher:
    def __init__(
        self,
        *,
        data_dir: str | None = None,
        filter_name: str | None = None,
        sender: str | None = None,
        subject: str | None = None,
        since_date: str | None = None,
        before_date: str | None = None,
        mailbox_name: str | None = None,
        from_uid: int | None = None,
        no_persist: bool = False,
    ):
        """Initialize fetcher from shared + agent config."""
        self.runtime = load_runtime_context(
            __file__,
            data_dir_override=data_dir,
            require_agent_config=True,
            require_external_data_dir=True,
        )
        self.config_path = self.runtime.global_config_path
        self.config = self.runtime.config
        self.data_dir = self.runtime.data_dir
        self.state = self._load_state()
        self.downloaded: list[dict[str, Any]] = []
        self.mailbox_counts: dict[str, int] = {}
        self.run_options = {
            "filter": self._clean_value(filter_name),
            "sender": self._clean_value(sender),
            "subject": self._clean_value(subject),
            "since_date": self._clean_value(since_date),
            "before_date": self._clean_value(before_date),
            "mailbox": self._clean_value(mailbox_name),
            "from_uid": from_uid,
            "no_persist": bool(no_persist),
        }
        self.active_filter = self._resolve_active_filter()

    @staticmethod
    def _clean_value(raw: Any) -> str | None:
        if raw is None:
            return None
        value = str(raw).strip()
        return value or None

    def _load_config(self) -> dict:
        return self.runtime.config

    def _normalize_state(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        raw = payload if isinstance(payload, dict) else {}
        filters_payload = raw.get("filters")
        if isinstance(filters_payload, dict):
            normalized_filters: dict[str, dict[str, Any]] = {}
            for filter_name, filter_state in filters_payload.items():
                mailboxes = {}
                if isinstance(filter_state, dict):
                    mailboxes_raw = filter_state.get("mailboxes", {})
                    if isinstance(mailboxes_raw, dict):
                        mailboxes = mailboxes_raw
                normalized_filters[str(filter_name)] = {"mailboxes": mailboxes}
            if normalized_filters:
                return {"filters": normalized_filters}

        mailboxes = raw.get("mailboxes", {})
        if not isinstance(mailboxes, dict):
            mailboxes = {}
        return {"filters": {"default": {"mailboxes": mailboxes}}}

    def _load_state(self) -> dict[str, Any]:
        state_file = self.config.get("mail", {}).get("state_file", "state.json")
        state_path = self.data_dir / state_file
        if state_path.exists():
            return self._normalize_state(json.loads(state_path.read_text()))
        return self._normalize_state({})

    def _save_state(self) -> None:
        state_file = self.config.get("mail", {}).get("state_file", "state.json")
        state_path = self.data_dir / state_file
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = state_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(state_path)

    def _get_sleep_seconds(self) -> float:
        """Global pause between _process_email iterations."""
        raw = self.config.get("mail", {}).get("fetch", {}).get("sleep_seconds", 0.5)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.5
        return max(0.0, value)

    def _get_filter_bucket(self, filter_name: str) -> dict[str, Any]:
        filters = self.state.setdefault("filters", {})
        filter_bucket = filters.setdefault(filter_name, {"mailboxes": {}})
        mailboxes = filter_bucket.setdefault("mailboxes", {})
        if not isinstance(mailboxes, dict):
            filter_bucket["mailboxes"] = {}
        return filter_bucket

    def _get_mailbox_state(self, mailbox_name: str, filter_name: str) -> dict[str, Any]:
        filter_bucket = self._get_filter_bucket(filter_name)
        mailboxes = filter_bucket.setdefault("mailboxes", {})
        mailbox_state = mailboxes.setdefault(mailbox_name, {})
        if not isinstance(mailbox_state, dict):
            mailboxes[mailbox_name] = {}
        return mailboxes[mailbox_name]

    def _get_last_uid(self, mailbox_name: str, filter_name: str) -> int:
        return int(self._get_mailbox_state(mailbox_name, filter_name).get("last_uid", 0))

    def _get_last_received_date(self, mailbox_name: str, filter_name: str) -> str | None:
        raw = self._get_mailbox_state(mailbox_name, filter_name).get("last_received_date")
        return self._clean_value(raw)

    def _update_last_uid(self, mailbox_name: str, filter_name: str, uid: int) -> None:
        mailbox_state = self._get_mailbox_state(mailbox_name, filter_name)
        mailbox_state["last_uid"] = uid
        mailbox_state["last_check"] = datetime.now().isoformat()

    def _update_last_received_date(
        self,
        mailbox_name: str,
        filter_name: str,
        timestamp_utc: str | None,
    ) -> None:
        """Persist last received message date (UTC day) in mailbox state."""
        if not timestamp_utc:
            return
        raw = str(timestamp_utc).strip()
        if not raw:
            return
        date_only = raw.split("T", 1)[0] if "T" in raw else raw[:10]
        mailbox_state = self._get_mailbox_state(mailbox_name, filter_name)
        mailbox_state["last_received_date"] = date_only

    @staticmethod
    def _to_imap_date(raw_value: str | None) -> str | None:
        """Convert date string to IMAP date format DD-Mon-YYYY."""
        if not raw_value:
            return None
        value = str(raw_value).strip()
        if not value:
            return None
        if re.fullmatch(r"\d{1,2}-[A-Za-z]{3}-\d{4}", value):
            return value
        try:
            dt = datetime.strptime(value, "%Y-%m-%d")
            return dt.strftime("%d-%b-%Y")
        except ValueError:
            return None

    def _resolve_filter_profiles(self) -> tuple[str, dict[str, dict[str, str]]]:
        filters_cfg = self.config.get("mail", {}).get("filters", {})
        profiles: dict[str, dict[str, str]] = {}

        explicit_profiles = filters_cfg.get("profiles", {})
        if isinstance(explicit_profiles, dict):
            for name, raw_profile in explicit_profiles.items():
                if not isinstance(raw_profile, dict):
                    continue
                profiles[str(name)] = {
                    key: value
                    for key in ("sender", "subject", "since_date", "before_date")
                    if (value := self._clean_value(raw_profile.get(key))) is not None
                }

        legacy_profile = {
            key: value
            for key in ("sender", "subject", "since_date", "before_date")
            if (value := self._clean_value(filters_cfg.get(key))) is not None
        }
        if "default" in profiles:
            merged_default = dict(legacy_profile)
            merged_default.update(profiles["default"])
            profiles["default"] = merged_default
        elif legacy_profile:
            profiles["default"] = legacy_profile

        if not profiles:
            profiles["default"] = {}

        default_name = self._clean_value(filters_cfg.get("default")) or "default"
        if default_name not in profiles:
            available = ", ".join(sorted(profiles))
            raise ValueError(
                f'Default filter "{default_name}" is not configured. Available filters: {available}'
            )
        return default_name, profiles

    def _resolve_active_filter(self) -> dict[str, str]:
        default_name, profiles = self._resolve_filter_profiles()
        selected_name = self.run_options.get("filter") or default_name
        if selected_name not in profiles:
            available = ", ".join(sorted(profiles))
            raise ValueError(
                f'Unknown filter "{selected_name}". Available filters: {available}'
            )

        active = dict(profiles[selected_name])
        for key in ("sender", "subject", "since_date", "before_date"):
            override = self.run_options.get(key)
            if override is not None:
                active[key] = override
        active["name"] = selected_name
        return active

    def _uses_ad_hoc_overrides(self) -> bool:
        return any(
            self.run_options.get(key) is not None
            for key in ("sender", "subject", "since_date", "before_date")
        )

    def _should_persist_state(self, *, dry_run: bool) -> bool:
        if dry_run:
            return False
        if self.run_options.get("no_persist"):
            return False
        if self.run_options.get("from_uid") is not None:
            return False
        if self._uses_ad_hoc_overrides():
            return False
        return True

    def _effective_since(self, mailbox_name: str, filter_name: str) -> str | None:
        explicit_since = self.active_filter.get("since_date")
        if explicit_since:
            return explicit_since
        if self._uses_ad_hoc_overrides():
            return None
        since_mode = str(self.config.get("mail", {}).get("since", "off")).strip().lower()
        if since_mode != "on":
            return None
        return self._get_last_received_date(mailbox_name, filter_name)

    def _effective_last_uid(self, mailbox_name: str, filter_name: str) -> int:
        if self.run_options.get("from_uid") is not None:
            return int(self.run_options["from_uid"])
        return self._get_last_uid(mailbox_name, filter_name)

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

        text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</(p|div|tr|li|h[1-6])>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = html_mod.unescape(text)
        lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in lines if line]
        return "\n".join(lines)

    @staticmethod
    def _safe_filename(filename: str) -> str:
        """Sanitize attachment filename for local filesystem writes."""
        name = str(filename).strip()
        # Replace path separators and control chars that break writes.
        name = re.sub(r"[\\/]+", " - ", name)
        name = re.sub(r"[\x00-\x1f]+", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name or "attachment.bin"

    @staticmethod
    def _sender_criteria(sender: str | None) -> list[str]:
        sender_value = (sender or "").strip()
        if not sender_value:
            return []
        if "@" in sender_value:
            local_part, domain_part = sender_value.split("@", 1)
            return [f'FROM "{local_part}"', f'FROM "{domain_part}"']
        return [f'FROM "{sender_value}"']

    @staticmethod
    def _criteria_has_nonascii(criteria: list[str]) -> bool:
        return any(not value.isascii() for value in criteria)

    @staticmethod
    def _extract_uid(fetch_response: Any) -> int | None:
        if not fetch_response:
            return None
        for item in fetch_response:
            if not isinstance(item, tuple) or not item:
                continue
            header = item[0]
            if isinstance(header, bytes):
                match = re.search(rb"UID (\d+)", header)
                if match:
                    return int(match.group(1))
            elif isinstance(header, str):
                match = re.search(r"UID (\d+)", header)
                if match:
                    return int(match.group(1))
        return None

    def _search_uids(self, conn, criteria: list[str]) -> list[bytes]:
        if not criteria:
            return []

        if self._criteria_has_nonascii(criteria):
            encoded = [value.encode("utf-8") for value in criteria]
            typ, data = conn.search("UTF-8", *encoded)
            if typ != "OK" or not data or not data[0]:
                return []

            uid_bytes: list[bytes] = []
            for sequence_id in data[0].split():
                _, fetch_response = conn.fetch(sequence_id, "(UID)")
                uid = self._extract_uid(fetch_response)
                if uid is None:
                    continue
                uid_bytes.append(str(uid).encode("ascii"))
            return uid_bytes

        typ, uid_data = conn.uid("SEARCH", None, *criteria)
        if typ != "OK" or not uid_data or not uid_data[0]:
            return []
        return list(uid_data[0].split())

    def _search_emails(
        self,
        conn,
        sender: str | None,
        last_uid: int,
        *,
        subject: str | None = None,
        since: str | None = None,
        before: str | None = None,
    ) -> list[tuple[int, bytes]]:
        """Search for new emails matching the current filter after last_uid."""
        criteria: list[str] = []
        imap_since = self._to_imap_date(since)
        if imap_since:
            criteria.extend(["SINCE", imap_since])

        imap_before = self._to_imap_date(before)
        if imap_before:
            criteria.extend(["BEFORE", imap_before])

        criteria.extend(self._sender_criteria(sender))

        subject_value = (subject or "").strip()
        if subject_value:
            criteria.append(f'SUBJECT "{subject_value}"')

        if not criteria:
            return []

        result = []
        for uid_bytes in self._search_uids(conn, criteria):
            uid = int(uid_bytes)
            if uid <= last_uid:
                continue
            result.append((uid, uid_bytes))

        return sorted(result, key=lambda item: item[0])

    def _process_email(self, conn, uid_bytes: bytes, uid: int, mailbox_name: str) -> dict | None:
        """Fetch a single email and write to incoming/ directory.

        Saves email body (text + HTML), attachments, and generic metadata.
        No business logic — downstream skills enrich meta.json as needed.
        """
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        now_date = datetime.now().strftime("%Y-%m-%d")
        dir_name = f"{now_date}_{mailbox_name}_uid{uid}"
        email_dir: Path | None = None

        meta = {
            "imap_uid": uid,
            "mailbox": mailbox_name,
            "subject": "",
            "sender": "",
            "timestamp": now_utc,
            "attachments": [],
            "dir_name": dir_name,
            "partial": False,
        }

        try:
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
                timestamp = now_utc
                date_formatted = now_date

            # Create canonical directory once (no temporary/orphan dir).
            email_dir = self.data_dir / "incoming" / f"{date_formatted}_{mailbox_name}_uid{uid}"
            email_dir.mkdir(parents=True, exist_ok=True)

            meta["subject"] = subject
            meta["sender"] = sender
            meta["timestamp"] = timestamp
            meta["dir_name"] = email_dir.name

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
            if body_for_text:
                (email_dir / "email_body.txt").write_text(body_for_text, encoding="utf-8")
            if email_body_html:
                (email_dir / "email_body.html").write_text(email_body_html, encoding="utf-8")

            # Download attachments (preserve original filename semantically, sanitize for fs)
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                if part.get("Content-Disposition") is None:
                    continue
                filename = part.get_filename()
                if not filename:
                    continue
                decoded = self._decode_header(filename)
                safe_name = self._safe_filename(decoded)
                try:
                    (email_dir / safe_name).write_bytes(part.get_payload(decode=True))
                    meta["attachments"].append(safe_name)
                except Exception as exc:
                    meta["partial"] = True
                    logger.error(
                        f"Attachment save failed UID {uid}: {decoded} -> {safe_name}: {exc}"
                    )

            return meta
        except Exception as exc:
            meta["partial"] = True
            meta["error"] = str(exc)
            logger.error(f"Failed to fully process UID {uid}: {exc}")
            return meta
        finally:
            # Always persist metadata, even for partial/failed message processing.
            if email_dir is None:
                email_dir = self.data_dir / "incoming" / f"{now_date}_{mailbox_name}_uid{uid}"
                email_dir.mkdir(parents=True, exist_ok=True)
                meta["dir_name"] = email_dir.name
            (email_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _resolve_mailboxes(self) -> list[dict[str, str]]:
        accounts = list(self.config.get("accounts", []))
        requested_mailbox = self.run_options.get("mailbox")
        if requested_mailbox is None:
            return accounts

        selected = [account for account in accounts if account.get("name") == requested_mailbox]
        if selected:
            return selected

        available = ", ".join(account.get("name", "") for account in accounts) or "<none>"
        raise ValueError(
            f'Unknown mailbox "{requested_mailbox}". Available mailboxes: {available}'
        )

    def fetch_mailbox(
        self,
        mailbox_config: dict,
        max_messages: int | None = None,
        dry_run: bool = False,
    ) -> int:
        """Fetch emails from a single mailbox.

        Args:
            mailbox_config: Mailbox config entry with name/email.
            max_messages: Optional cap for this mailbox in current run.

        Returns:
            Number of successfully fetched messages.
        """
        mailbox_name = mailbox_config["name"]
        email_addr = mailbox_config["email"]
        filter_name = self.active_filter["name"]

        logger.info(
            f"Checking mailbox: {email_addr} ({mailbox_name}) using filter {filter_name}"
        )

        # Load token from data_dir/auth/{name}.token
        try:
            token_info = resolve_token(
                account=mailbox_name,
                skill="mail",
                data_dir=self.data_dir,
                config=self.config,
                required_scopes=["mail:imap_ro"],
            )
        except Exception as exc:
            logger.error(str(exc))
            return 0
        token = token_info.token

        # Connect with retry
        conn = None
        for attempt in range(3):
            try:
                conn = self._connect_imap(email_addr, token)
                logger.info("Connected to IMAP")
                break
            except Exception as exc:
                logger.warning(f"Connection attempt {attempt + 1} failed: {exc}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
        if conn is None:
            logger.error("All connection attempts failed")
            return 0

        last_uid = self._effective_last_uid(mailbox_name, filter_name)
        logger.info(f"Last processed UID: {last_uid}")

        sender = self.active_filter.get("sender")
        subject = self.active_filter.get("subject")
        since = self._effective_since(mailbox_name, filter_name)
        before = self.active_filter.get("before_date")
        if not any([sender, subject, since, before]):
            logger.error("No mail filter criteria configured for this run")
            conn.logout()
            return 0

        try:
            matching = self._search_emails(
                conn,
                sender,
                last_uid,
                subject=subject,
                since=since,
                before=before,
            )
        except Exception as exc:
            logger.error(f"Search failed: {exc}")
            conn.logout()
            return 0

        if max_messages is not None:
            matching = matching[:max_messages]
            logger.info(f"Found {len(matching)} new emails (capped by --num)")
        else:
            logger.info(f"Found {len(matching)} new emails")

        if dry_run:
            for uid, uid_bytes in matching:
                try:
                    _, msg_data = conn.uid(
                        "FETCH",
                        uid_bytes,
                        "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])",
                    )
                    raw_header = msg_data[0][1]
                    msg = email.message_from_bytes(raw_header)
                    subject_value = self._decode_header(msg.get("Subject", ""))
                    sender_value = self._decode_header(msg.get("From", ""))
                    date_str = msg.get("Date", "")
                    try:
                        date_parsed = email.utils.parsedate_to_datetime(date_str)
                        timestamp = date_parsed.astimezone(timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        )
                    except Exception:
                        timestamp = ""
                    self.downloaded.append(
                        {
                            "imap_uid": uid,
                            "mailbox": mailbox_name,
                            "subject": subject_value,
                            "sender": sender_value,
                            "timestamp": timestamp,
                            "dry_run": True,
                            "filter": filter_name,
                        }
                    )
                except Exception as exc:
                    logger.warning(f"Dry-run header fetch failed for UID {uid}: {exc}")
            conn.logout()
            logger.info("Disconnected (dry-run)")
            return 0

        fetched_count = 0
        persist_state = self._should_persist_state(dry_run=dry_run)

        # Process each email
        sleep_seconds = self._get_sleep_seconds()

        for idx, (uid, uid_bytes) in enumerate(matching):
            logger.info(f"Processing UID {uid}...")
            try:
                meta = self._process_email(conn, uid_bytes, uid, mailbox_name)
                if meta:
                    meta["filter"] = filter_name
                    self.downloaded.append(meta)
                    if persist_state:
                        self._update_last_uid(mailbox_name, filter_name, uid)
                        self._update_last_received_date(
                            mailbox_name,
                            filter_name,
                            meta.get("timestamp"),
                        )
                        self._save_state()
                    fetched_count += 1
                    logger.info(
                        f"  OK: {meta['subject'][:50]} "
                        f"attachments={len(meta['attachments'])}"
                    )
            except Exception as exc:
                logger.error(f"  Failed UID {uid}: {exc}")

            # Throttle between iterations (except after the last message).
            if idx < len(matching) - 1 and sleep_seconds > 0:
                time.sleep(sleep_seconds)

        conn.logout()
        logger.info("Disconnected")
        return fetched_count

    def fetch_all(self, num_messages: int | None = None, dry_run: bool = False) -> list[dict]:
        """Fetch from all configured mailboxes.

        Args:
            num_messages: Optional global cap for fetched messages in this run.
        """
        remaining = num_messages
        self.mailbox_counts = {}

        for mailbox_config in self._resolve_mailboxes():
            if remaining is not None and remaining <= 0:
                logger.info("Reached --num cap; stopping mailbox scan")
                self.mailbox_counts[mailbox_config["name"]] = 0
                break

            fetched = self.fetch_mailbox(
                mailbox_config,
                max_messages=remaining,
                dry_run=dry_run,
            )
            self.mailbox_counts[mailbox_config["name"]] = fetched
            if remaining is not None:
                remaining -= fetched if not dry_run else 0

        return self.downloaded


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch emails from Yandex Mail")
    parser.add_argument(
        "--num",
        type=int,
        default=None,
        help="Maximum number of new messages to fetch in this run (global cap across mailboxes)",
    )
    parser.add_argument(
        "--filter",
        help="Named mail filter profile to use for this run",
    )
    parser.add_argument(
        "--sender",
        help="Override the sender criterion for this run only",
    )
    parser.add_argument(
        "--subject",
        help="Override the subject criterion for this run only",
    )
    parser.add_argument(
        "--since-date",
        help="Override SINCE search date (YYYY-MM-DD or DD-Mon-YYYY)",
    )
    parser.add_argument(
        "--before-date",
        help="Add BEFORE search date (YYYY-MM-DD or DD-Mon-YYYY)",
    )
    parser.add_argument(
        "--mailbox",
        help="Run only for the named configured mailbox",
    )
    parser.add_argument(
        "--from-uid",
        type=int,
        help="Start this run from the given UID floor without persisting state",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not update state.json after this run",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show pending emails without writing incoming/ or updating state",
    )
    parser.add_argument(
        "--data-dir",
        help="Explicit Yandex data directory override for non-workspace execution",
    )
    args = parser.parse_args()

    if args.num is not None and args.num <= 0:
        parser.error("--num must be a positive integer")
    if args.from_uid is not None and args.from_uid <= 0:
        parser.error("--from-uid must be a positive integer")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    try:
        fetcher = EmailFetcher(
            data_dir=args.data_dir,
            filter_name=args.filter,
            sender=args.sender,
            subject=args.subject,
            since_date=args.since_date,
            before_date=args.before_date,
            mailbox_name=args.mailbox,
            from_uid=args.from_uid,
            no_persist=args.no_persist,
        )
        results = fetcher.fetch_all(num_messages=args.num, dry_run=args.dry_run)
    except ValueError as exc:
        parser.error(str(exc))

    pending_rows = []
    if args.dry_run:
        pending_rows = [
            {
                "uid": item.get("imap_uid"),
                "mailbox": item.get("mailbox"),
                "sender": item.get("sender", ""),
                "subject": item.get("subject", ""),
                "timestamp": item.get("timestamp", ""),
                "filter": item.get("filter", ""),
            }
            for item in results
        ]

    print(
        json.dumps(
            {
                "dry_run": bool(args.dry_run),
                "filter": fetcher.active_filter["name"],
                "persist_state": fetcher._should_persist_state(dry_run=args.dry_run),
                "fetched_total": 0 if args.dry_run else len(results),
                "pending_total": len(pending_rows) if args.dry_run else 0,
                "pending": pending_rows if args.dry_run else [],
                "mailboxes": fetcher.mailbox_counts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
