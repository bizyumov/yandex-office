#!/usr/bin/env python3
"""
Yandex Mail fetcher via IMAP XOAUTH2.

Connects to Yandex Mail, fetches emails from configured accounts, downloads
attachments and email body into structured `incoming/` directories.

Designed to be run as a cron job. State is persisted after each email
to prevent data loss on interruption.

Output structure per email:
    {data_dir}/incoming/{filter}/{YYYY-MM-DD}_{account}_uid{N}/
        {original_attachment_filename}   # Preserved original name
        email_body.txt                   # HTML→text converted body
        email_body.html                  # Raw HTML body (if available)
        meta.json                        # Metadata (no business logic)
"""

from __future__ import annotations

import argparse
import email
import email.utils
import hashlib
import imaplib
import json
import logging
import os
import re
import requests
import ssl
import sys
import time
from datetime import datetime, timezone
from email.header import decode_header
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.api import YandexApiContext, yandex_api_method
from common.config import load_runtime_context

logger = logging.getLogger("mail")
FILTER_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
LEGACY_FILTER_NAME = "telemost"
AD_HOC_FILTER_NAME = "default"
REMOVED_FILTER_SCHEMA_KEY = "profiles"


class EmailFetcher:
    """Fetch Yandex Mail messages for token-backed Yandex accounts."""

    def __init__(
        self,
        *,
        data_dir: str | None = None,
        filter_name: str | None = None,
        sender: str | None = None,
        subject: str | None = None,
        since_date: str | None = None,
        before_date: str | None = None,
        account_name: str | None = None,
        from_uid: int | None = None,
        uid: int | None = None,
        no_persist: bool = False,
        preview_body: bool = False,
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
        self.account_counts: dict[str, int] = {}
        self.filter_counts: dict[str, int] = {}
        self.run_options = {
            "filter": self._clean_value(filter_name),
            "sender": self._clean_value(sender),
            "subject": self._clean_value(subject),
            "since_date": self._clean_value(since_date),
            "before_date": self._clean_value(before_date),
            "account": self._clean_value(account_name),
            "from_uid": from_uid,
            "uid": uid,
            "no_persist": bool(no_persist),
            "preview_body": bool(preview_body),
        }
        self.named_filters = self._resolve_named_filters()
        self.run_filters = self._resolve_run_filters()
        self.active_filter = self.run_filters[0] if len(self.run_filters) == 1 else None

    @staticmethod
    def _clean_value(raw: Any) -> str | None:
        """Normalize empty CLI/config values to None."""
        if raw is None:
            return None
        value = str(raw).strip()
        return value or None

    @staticmethod
    def _validate_filter_key(name: str) -> str:
        """Validate a configured mail filter schema key."""
        if name == AD_HOC_FILTER_NAME:
            raise ValueError(
                f'"{AD_HOC_FILTER_NAME}" is reserved for ad-hoc runs; use a real filter key such as "{LEGACY_FILTER_NAME}"'
            )
        if name == REMOVED_FILTER_SCHEMA_KEY:
            raise ValueError(
                f'"{REMOVED_FILTER_SCHEMA_KEY}" was removed; define filters directly under mail.filters'
            )
        if not FILTER_KEY_RE.fullmatch(name):
            raise ValueError(
                "Filter names must use lowercase English schema keys only: "
                "letters, digits, and underscores, starting with a letter"
            )
        return name

    def _load_config(self) -> dict:
        """Return the merged runtime configuration."""
        return self.runtime.config

    def _normalize_state(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        """Normalize cursor state to the current account-keyed format."""
        raw = payload if isinstance(payload, dict) else {}
        filters_payload = raw.get("filters")
        if isinstance(filters_payload, dict):
            normalized_filters: dict[str, dict[str, Any]] = {}
            for filter_name, filter_state in filters_payload.items():
                accounts = filter_state.get("accounts", {}) if isinstance(filter_state, dict) else {}
                normalized_name = (
                    LEGACY_FILTER_NAME if str(filter_name) == AD_HOC_FILTER_NAME else str(filter_name)
                )
                bucket = normalized_filters.setdefault(normalized_name, {"accounts": {}})
                bucket_accounts = bucket.setdefault("accounts", {})
                if isinstance(accounts, dict):
                    bucket_accounts.update(accounts)
            if normalized_filters:
                return {"filters": normalized_filters}

        accounts = raw.get("accounts")
        if not isinstance(accounts, dict):
            accounts = {}
        return {"filters": {LEGACY_FILTER_NAME: {"accounts": accounts}}}

    def _load_state(self) -> dict[str, Any]:
        """Load persistent mail cursor state from the data directory."""
        state_file = self.config.get("mail", {}).get("state_file", "state.json")
        state_path = self.data_dir / state_file
        if state_path.exists():
            return self._normalize_state(json.loads(state_path.read_text()))
        return self._normalize_state({})

    def _save_state(self) -> None:
        """Atomically persist the normalized mail cursor state."""
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
        """Return the mutable cursor bucket for a mail filter."""
        filters = self.state.setdefault("filters", {})
        filter_bucket = filters.setdefault(filter_name, {"accounts": {}})
        accounts = filter_bucket.setdefault("accounts", {})
        if not isinstance(accounts, dict):
            filter_bucket["accounts"] = {}
        return filter_bucket

    def _get_account_state(self, account_name: str, filter_name: str) -> dict[str, Any]:
        """Return the mutable cursor state for one account/filter pair."""
        filter_bucket = self._get_filter_bucket(filter_name)
        accounts = filter_bucket.setdefault("accounts", {})
        account_state = accounts.setdefault(account_name, {})
        if not isinstance(account_state, dict):
            accounts[account_name] = {}
        return accounts[account_name]

    def _get_last_uid(self, account_name: str, filter_name: str) -> int:
        """Return the last processed UID for one account/filter pair."""
        return int(self._get_account_state(account_name, filter_name).get("last_uid", 0))

    def _get_last_received_date(self, account_name: str, filter_name: str) -> str | None:
        """Return the last received UTC date cursor for one account/filter pair."""
        raw = self._get_account_state(account_name, filter_name).get("last_received_date")
        return self._clean_value(raw)

    def _update_last_uid(self, account_name: str, filter_name: str, uid: int) -> None:
        """Persist the last processed UID for one account/filter pair."""
        account_state = self._get_account_state(account_name, filter_name)
        account_state["last_uid"] = uid
        account_state["last_check"] = datetime.now().isoformat()

    def _update_last_received_date(
        self,
        account_name: str,
        filter_name: str,
        timestamp_utc: str | None,
    ) -> None:
        """Persist last received message date in the account cursor state."""
        if not timestamp_utc:
            return
        raw = str(timestamp_utc).strip()
        if not raw:
            return
        date_only = raw.split("T", 1)[0] if "T" in raw else raw[:10]
        account_state = self._get_account_state(account_name, filter_name)
        account_state["last_received_date"] = date_only

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

    @classmethod
    def _normalize_filter_branch(cls, raw_branch: Any) -> dict[str, Any] | None:
        """Normalize one atomic OR branch and attach its stable state key."""
        if not isinstance(raw_branch, dict):
            return None
        branch = {
            key: value
            for key in ("sender", "subject", "since_date", "before_date")
            if (value := cls._clean_value(raw_branch.get(key))) is not None
        }
        if not branch:
            return None
        canonical = json.dumps(branch, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        branch["branch_key"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return branch

    def _resolve_named_filters(self) -> dict[str, dict[str, Any]]:
        """Resolve configured named filters into normalized filter records."""
        filters_cfg = self.config.get("mail", {}).get("filters", {})
        filters: dict[str, dict[str, Any]] = {}
        legacy_keys = {"sender", "subject", "since_date", "before_date"}

        for name, raw_filter in filters_cfg.items():
            if name in legacy_keys or not isinstance(raw_filter, dict):
                continue
            raw_name = str(name)
            key_name = self._validate_filter_key(raw_name)
            existing = filters.get(key_name, {})
            merged_filter = {
                "name": key_name,
                "enabled": bool(raw_filter.get("enabled", existing.get("enabled", True))),
                **{
                    key: value
                    for key in ("sender", "subject", "since_date", "before_date")
                    if (value := self._clean_value(existing.get(key))) is not None
                },
                **{
                    key: value
                    for key in ("sender", "subject", "since_date", "before_date")
                    if (value := self._clean_value(raw_filter.get(key))) is not None
                },
            }
            raw_any = raw_filter.get("any")
            if isinstance(raw_any, list):
                branches = [
                    branch
                    for raw_branch in raw_any
                    if (branch := self._normalize_filter_branch(raw_branch)) is not None
                ]
                if branches:
                    merged_filter.pop("sender", None)
                    merged_filter.pop("subject", None)
                    merged_filter.pop("since_date", None)
                    merged_filter.pop("before_date", None)
                    merged_filter["any"] = branches
            filters[key_name] = merged_filter

        legacy_profile = {
            key: value
            for key in ("sender", "subject", "since_date", "before_date")
            if (value := self._clean_value(filters_cfg.get(key))) is not None
        }
        if legacy_profile:
            merged_legacy = {
                "name": LEGACY_FILTER_NAME,
                "enabled": filters.get(LEGACY_FILTER_NAME, {}).get("enabled", True),
                **legacy_profile,
                **{
                    key: value
                    for key, value in filters.get(LEGACY_FILTER_NAME, {}).items()
                    if key not in {"name", "enabled"}
                },
            }
            filters[LEGACY_FILTER_NAME] = merged_legacy

        return filters

    def _resolve_run_filters(self) -> list[dict[str, Any]]:
        """Choose the filter set for this invocation."""
        explicit_filter = self.run_options.get("filter")
        has_raw_overrides = any(
            self.run_options.get(key) is not None
            for key in ("sender", "subject", "since_date", "before_date", "uid")
        )

        if explicit_filter is not None:
            if explicit_filter not in self.named_filters:
                available = ", ".join(sorted(self.named_filters))
                raise ValueError(
                    f'Unknown filter "{explicit_filter}". Available filters: {available}'
                )
            selected = dict(self.named_filters[explicit_filter])
            for key in ("sender", "subject", "since_date", "before_date"):
                override = self.run_options.get(key)
                if override is not None:
                    selected[key] = override
            return [selected]

        if has_raw_overrides:
            ad_hoc = {"name": AD_HOC_FILTER_NAME, "enabled": True}
            for key in ("sender", "subject", "since_date", "before_date"):
                override = self.run_options.get(key)
                if override is not None:
                    ad_hoc[key] = override
            return [ad_hoc]

        return [
            dict(filter_def)
            for filter_def in self.named_filters.values()
            if filter_def.get("enabled", True)
        ]

    def _uses_ad_hoc_overrides(self) -> bool:
        """Return true when this invocation should not use stored cursors."""
        return any(
            self.run_options.get(key) is not None
            for key in ("sender", "subject", "since_date", "before_date", "uid")
        )

    def _should_persist_state(self, *, dry_run: bool) -> bool:
        """Return whether this invocation may advance persistent cursors."""
        if dry_run:
            return False
        if self.run_options.get("no_persist"):
            return False
        if self.run_options.get("from_uid") is not None:
            return False
        if self.run_options.get("uid") is not None:
            return False
        if self._uses_ad_hoc_overrides():
            return False
        return True

    def _effective_since(
        self,
        account_name: str,
        filter_name: str,
        run_filter: dict[str, Any],
    ) -> str | None:
        """Resolve the SINCE criterion for one account/filter pair."""
        explicit_since = run_filter.get("since_date")
        if explicit_since:
            return explicit_since
        if self._uses_ad_hoc_overrides():
            return None
        since_mode = str(self.config.get("mail", {}).get("since", "off")).strip().lower()
        if since_mode != "on":
            return None
        return self._get_last_received_date(account_name, filter_name)

    def _effective_last_uid(self, account_name: str, filter_name: str) -> int:
        """Resolve the UID floor for one account/filter pair."""
        if self.run_options.get("from_uid") is not None:
            return int(self.run_options["from_uid"])
        if self._uses_ad_hoc_overrides() and self.run_options.get("filter") is None:
            return 1
        return self._get_last_uid(account_name, filter_name)

    @staticmethod
    def _mail_credentials(ctx: YandexApiContext) -> tuple[str, str]:
        """Resolve verified email and bearer token from the API context."""
        if ctx.token_ref is None:
            raise RuntimeError("Mail API context is not token-bound")
        email_addr = str((ctx.token_data or {}).get("email") or "").strip()
        if not email_addr:
            raise RuntimeError("Mail token file is missing verified email")
        return email_addr, ctx.token_ref.token

    @yandex_api_method("mail.imap.authenticate", one_of=["mail:imap_full", "mail:imap_ro"])
    def _connect_imap(self, ctx: YandexApiContext) -> imaplib.IMAP4_SSL:
        """Authenticate to IMAP with the shared auth dispatcher token."""

        imap_cfg = self.config.get("imap", {})
        server = imap_cfg.get("server", "imap.yandex.com")
        port = imap_cfg.get("port", 993)

        email_addr, token = self._mail_credentials(ctx)
        auth_string = f"user={email_addr}\x01auth=Bearer {token}\x01\x01"
        context = ssl.create_default_context()
        conn = imaplib.IMAP4_SSL(server, port, ssl_context=context)
        conn.authenticate("XOAUTH2", lambda x: auth_string.encode())
        self._select_inbox(conn, ctx=ctx)
        return conn

    @yandex_api_method("mail.imap.select", one_of=["mail:imap_full", "mail:imap_ro"])
    def _select_inbox(
        self,
        conn: imaplib.IMAP4_SSL,
        *,
        ctx: YandexApiContext | None = None,
    ) -> None:
        """Select INBOX after authentication."""

        conn.select("INBOX")

    @staticmethod
    def _decode_header(header_value: str) -> str:
        """Decode an RFC 2047 message header into display text."""
        if header_value is None:
            return ""
        if not isinstance(header_value, (str, bytes)):
            header_value = str(header_value)
        if not header_value:
            return ""
        decoded_parts = decode_header(header_value)
        result = []
        for content, encoding in decoded_parts:
            if isinstance(content, bytes):
                content = content.decode(encoding or "utf-8", errors="replace")
            else:
                content = str(content)
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
    def _message_bodies(msg) -> tuple[str | None, str | None]:
        """Extract first text/plain and text/html bodies from a message."""
        email_body_text = None
        email_body_html = None
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            disposition = (part.get_content_disposition() or "").lower()
            if disposition == "attachment":
                continue
            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            if part.get_content_type() == "text/plain" and email_body_text is None:
                email_body_text = payload.decode(charset, errors="replace")
            elif part.get_content_type() == "text/html" and email_body_html is None:
                email_body_html = payload.decode(charset, errors="replace")
        return email_body_text, email_body_html

    @staticmethod
    def _safe_filename(filename: str) -> str:
        """Sanitize attachment filename for local filesystem writes."""
        name = str(filename).strip()
        # Replace path separators and control chars that break writes.
        name = re.sub(r"[\\/]+", " - ", name)
        name = re.sub(r"[\x00-\x1f]+", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name or "attachment.bin"

    @classmethod
    def _available_filename(cls, directory: Path, filename: str) -> str:
        """Return a sanitized filename that will not overwrite an existing file."""
        safe_name = cls._safe_filename(filename)
        candidate = safe_name
        stem = Path(safe_name).stem or "attachment"
        suffix = Path(safe_name).suffix
        index = 2
        while (directory / candidate).exists():
            candidate = f"{stem}-{index}{suffix}"
            index += 1
        return candidate

    @staticmethod
    def _normalize_attachment_meta(item: Any) -> dict[str, Any]:
        """Normalize new object attachments and legacy string attachments."""
        if isinstance(item, str):
            return {
                "original-filename": item,
                "saved-filename": item,
                "content-type": None,
                "size": None,
                "disposition": None,
                "content-id": None,
                "part-index": None,
            }
        if isinstance(item, dict):
            return {
                "original-filename": item.get("original-filename"),
                "saved-filename": item.get("saved-filename"),
                "content-type": item.get("content-type"),
                "size": item.get("size"),
                "disposition": item.get("disposition"),
                "content-id": item.get("content-id"),
                "part-index": item.get("part-index"),
            }
        return {
            "original-filename": None,
            "saved-filename": None,
            "content-type": None,
            "size": None,
            "disposition": None,
            "content-id": None,
            "part-index": None,
        }

    @classmethod
    def _normalize_attachments_meta(cls, attachments: Any) -> list[dict[str, Any]]:
        """Normalize a meta.json attachments field while accepting the legacy list[str] format."""
        if not isinstance(attachments, list):
            return []
        return [cls._normalize_attachment_meta(item) for item in attachments]

    @staticmethod
    def _sender_criteria(sender: str | None) -> list[str]:
        """Build IMAP FROM criteria from an email address or text fragment."""
        sender_value = (sender or "").strip()
        if not sender_value:
            return []
        if "@" in sender_value:
            local_part, domain_part = sender_value.split("@", 1)
            return [f'FROM "{local_part}"', f'FROM "{domain_part}"']
        return [f'FROM "{sender_value}"']

    @staticmethod
    def _imap_or(criteria: list[str]) -> list[str]:
        """Build a nested IMAP OR expression from single-key criteria."""
        if len(criteria) <= 1:
            return list(criteria)
        expression = [criteria[-1]]
        for criterion in reversed(criteria[:-1]):
            expression = ["OR", criterion, *expression]
        return expression

    @classmethod
    def _can_search_any_as_sender_or(cls, branches: list[dict[str, Any]]) -> bool:
        """Return true when OR branches can share one sender-only IMAP search."""
        if not branches:
            return False
        for branch in branches:
            sender = cls._clean_value(branch.get("sender"))
            if sender is None:
                return False
            # Full email addresses intentionally keep the existing two-key
            # local_part/domain_part workaround; do not flatten them into the
            # sender-domain OR path.
            if "@" in sender:
                return False
            if any(cls._clean_value(branch.get(key)) is not None for key in ("subject", "since_date", "before_date")):
                return False
        return True

    @classmethod
    def _sender_matches_header(cls, sender_filter: str | None, sender_header: str | None) -> bool:
        """Mirror existing FROM search semantics against a fetched From header."""
        criteria = cls._sender_criteria(sender_filter)
        haystack = (sender_header or "").casefold()
        for criterion in criteria:
            match = re.fullmatch(r'FROM\s+"(.*)"', criterion)
            needle = (match.group(1) if match else criterion).casefold()
            if needle not in haystack:
                return False
        return True

    @staticmethod
    def _normalize_subject_for_match(value: str | None) -> str:
        """Normalize subject text for Yandex IMAP/local matching quirks."""
        return (value or "").replace("Ё", "Е").replace("ё", "е").casefold()

    @staticmethod
    def _normalize_subject_for_imap(value: str) -> str:
        """Normalize subject search terms to match Yandex IMAP's ё/е indexing."""
        return value.replace("Ё", "Е").replace("ё", "е")

    @classmethod
    def _branch_matches_meta(cls, branch: dict[str, Any], meta: dict[str, Any]) -> bool:
        """Check whether a fetched message matches one normalized OR branch."""
        sender = cls._clean_value(branch.get("sender"))
        if sender is not None and not cls._sender_matches_header(sender, meta.get("sender")):
            return False

        subject = cls._clean_value(branch.get("subject"))
        if subject is not None and cls._normalize_subject_for_match(subject) not in cls._normalize_subject_for_match(str(meta.get("subject", ""))):
            return False

        timestamp = str(meta.get("timestamp") or "")
        message_date = timestamp.split("T", 1)[0] if "T" in timestamp else timestamp[:10]
        since = cls._clean_value(branch.get("since_date"))
        if since is not None and message_date and message_date < since[:10]:
            return False
        before = cls._clean_value(branch.get("before_date"))
        if before is not None and message_date and message_date >= before[:10]:
            return False

        return True

    @staticmethod
    def _criteria_has_nonascii(criteria: list[str]) -> bool:
        """Return true when search criteria need UTF-8 IMAP search."""
        return any(not value.isascii() for value in criteria)

    @staticmethod
    def _extract_uid(fetch_response: Any) -> int | None:
        """Extract a UID integer from an IMAP FETCH response."""
        if not fetch_response:
            return None
        for item in fetch_response:
            if isinstance(item, tuple):
                candidates = [part for part in item if isinstance(part, (bytes, str))]
            elif isinstance(item, (bytes, str)):
                candidates = [item]
            else:
                continue

            for candidate in candidates:
                if isinstance(candidate, bytes):
                    match = re.search(rb"UID (\d+)", candidate)
                    if match:
                        return int(match.group(1))
                else:
                    match = re.search(r"UID (\d+)", candidate)
                    if match:
                        return int(match.group(1))
        return None

    @staticmethod
    def _extract_message_bytes(fetch_response: Any) -> bytes | None:
        """Extract raw message bytes from an IMAP FETCH response."""
        if not fetch_response:
            return None

        for item in fetch_response:
            if isinstance(item, tuple):
                for part in item[1:]:
                    if isinstance(part, bytes):
                        return part
                    if isinstance(part, bytearray):
                        return bytes(part)
            elif isinstance(item, bytes) and b":" in item:
                return item
            elif isinstance(item, bytearray) and b":" in item:
                return bytes(item)

        return None

    def _get_output_max_inline_symbols(self) -> int:
        """Return the maximum dry-run JSON payload size to print inline."""
        raw = self.config.get("mail", {}).get("output", {}).get("max_inline_symbols", 2000)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 2000
        return max(1, value)

    def _get_output_dir(self) -> Path:
        """Create and return the dry-run spill output directory."""
        raw = self.config.get("mail", {}).get("output", {}).get("spill_dir", "latest-query")
        name = str(raw).strip() or "latest-query"
        path = self.data_dir / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _spill_payload_to_file(self, payload: dict[str, Any], *, prefix: str) -> Path:
        """Write a large dry-run payload to the configured spill directory."""
        output_dir = self._get_output_dir()
        for existing in output_dir.glob("*.json"):
            existing.unlink(missing_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output_path = output_dir / f"{prefix}_{timestamp}.json"
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return output_path

    def _search_uids(self, conn, criteria: list[str]) -> list[bytes]:
        """Search IMAP and return matching UID byte strings."""
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

    def _search_emails_by_criteria(
        self,
        conn,
        criteria: list[str],
        last_uid: int,
        *,
        max_uid: int | None = None,
    ) -> list[tuple[int, bytes]]:
        """Search for emails using pre-built IMAP criteria within UID bounds."""
        search_criteria = list(criteria)
        if max_uid is not None:
            if max_uid <= 0:
                return []
            search_criteria = ["UID", f"1:{max_uid}", *search_criteria]

        result = []
        for uid_bytes in self._search_uids(conn, search_criteria):
            uid = int(uid_bytes)
            if uid <= last_uid:
                continue
            if max_uid is not None and uid > max_uid:
                continue
            result.append((uid, uid_bytes))
        return sorted(result, key=lambda item: item[0])

    @yandex_api_method("mail.imap.search", one_of=["mail:imap_full", "mail:imap_ro"])
    def _search_emails(
        self,
        conn,
        sender: str | None,
        last_uid: int,
        *,
        subject: str | None = None,
        since: str | None = None,
        before: str | None = None,
        ctx: YandexApiContext | None = None,
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
            criteria.append(f'SUBJECT "{self._normalize_subject_for_imap(subject_value)}"')

        if not criteria:
            return []

        return self._search_emails_by_criteria(conn, criteria, last_uid)

    @yandex_api_method("mail.imap.fetch", one_of=["mail:imap_full", "mail:imap_ro"])
    def _fetch_message_data(
        self,
        conn,
        uid_bytes: bytes,
        query: str,
        *,
        ctx: YandexApiContext | None = None,
    ):
        """Fetch message data through the shared auth-dispatched IMAP boundary."""

        return conn.uid("FETCH", uid_bytes, query)

    def _process_email(
        self,
        conn,
        uid_bytes: bytes,
        uid: int,
        account_name: str,
        filter_name: str,
        *,
        ctx: YandexApiContext | None = None,
    ) -> dict | None:
        """Fetch a single email and write to incoming/ directory.

        Saves email body (text + HTML), attachments, and generic metadata.
        No business logic — downstream skills enrich meta.json as needed.
        """
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        now_date = datetime.now().strftime("%Y-%m-%d")
        dir_name = f"{now_date}_{account_name}_uid{uid}"
        email_dir: Path | None = None

        meta = {
            "imap_uid": uid,
            "account": account_name,
            "filter": filter_name,
            "subject": "",
            "sender": "",
            "timestamp": now_utc,
            "attachments": [],
            "body": {},
            "dir_name": dir_name,
            "partial": False,
        }

        try:
            _, msg_data = self._fetch_message_data(conn, uid_bytes, "(RFC822)", ctx=ctx)
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
            email_dir = (
                self.data_dir
                / "incoming"
                / filter_name
                / f"{date_formatted}_{account_name}_uid{uid}"
            )
            email_dir.mkdir(parents=True, exist_ok=True)

            meta["subject"] = subject
            meta["sender"] = sender
            meta["timestamp"] = timestamp
            meta["dir_name"] = email_dir.name
            meta["dir_relpath"] = str(email_dir.relative_to(self.data_dir / "incoming"))

            email_body_text, email_body_html = self._message_bodies(msg)

            body_for_text = email_body_text or (
                self._html_to_text(email_body_html) if email_body_html else ""
            )
            if body_for_text:
                (email_dir / "email_body.txt").write_text(body_for_text, encoding="utf-8")
                meta["body"]["text"] = "email_body.txt"
            if email_body_html:
                (email_dir / "email_body.html").write_text(email_body_html, encoding="utf-8")
                meta["body"]["html"] = "email_body.html"

            # Download non-body file parts (preserve original filename semantically, sanitize for fs)
            for part_index, part in enumerate(msg.walk()):
                if part.get_content_maintype() == "multipart":
                    continue
                disposition = (part.get_content_disposition() or "").lower()
                content_type = part.get_content_type()
                is_text_body = content_type in {"text/plain", "text/html"} and disposition != "attachment"
                if is_text_body:
                    continue
                filename = part.get_filename()
                if not filename:
                    continue
                decoded = self._decode_header(filename)
                safe_name = self._available_filename(email_dir, decoded)
                try:
                    payload = part.get_payload(decode=True) or b""
                    (email_dir / safe_name).write_bytes(payload)
                    detail = {
                        "original-filename": decoded,
                        "saved-filename": safe_name,
                        "content-type": content_type,
                        "size": len(payload),
                        "disposition": disposition or None,
                        "content-id": part.get("Content-ID"),
                        "part-index": part_index,
                    }
                    meta["attachments"].append(detail)
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
                email_dir = (
                    self.data_dir
                    / "incoming"
                    / filter_name
                    / f"{now_date}_{account_name}_uid{uid}"
                )
                email_dir.mkdir(parents=True, exist_ok=True)
                meta["dir_name"] = email_dir.name
                meta["dir_relpath"] = str(email_dir.relative_to(self.data_dir / "incoming"))
            (email_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _resolve_accounts(self) -> list[dict[str, str]]:
        """Return account records selected for this invocation."""
        accounts = list(self.config.get("accounts", []))
        requested_account = self.run_options.get("account")
        available = ", ".join(account.get("name", "") for account in accounts) or "<none>"
        if requested_account is None:
            if self.run_options.get("uid") is not None and len(accounts) != 1:
                raise ValueError(
                    f"--uid requires --account when aliases are ambiguous: {available}"
                )
            return accounts

        selected = [account for account in accounts if account.get("name") == requested_account]
        if selected:
            return selected

        raise ValueError(
            f'Unknown account alias "{requested_account}". Available aliases: {available}'
        )

    def fetch_account(
        self,
        account_config: dict,
        run_filter: dict[str, Any],
        max_messages: int | None = None,
        dry_run: bool = False,
    ) -> int:
        """Fetch emails from a single Yandex account.

        Args:
            account_config: Account config entry with name/email.
            max_messages: Optional cap for this account in current run.

        Returns:
            Number of successfully fetched messages.
        """
        account_name = account_config["name"]
        filter_name = run_filter["name"]

        logger.info(
            f"Checking account: {account_config['email']} ({account_name}) using filter {filter_name}"
        )

        api_ctx = YandexApiContext(
            account=account_name,
            data_dir=self.data_dir,
            config=self.config,
            session=requests.Session(),
        )

        # Connect with retry
        conn = None
        for attempt in range(3):
            try:
                conn = self._connect_imap(api_ctx)
                logger.info("Connected to IMAP")
                break
            except Exception as exc:
                logger.warning(f"Connection attempt {attempt + 1} failed: {exc}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
        if conn is None:
            logger.error("All connection attempts failed")
            return 0

        any_branches = run_filter.get("any") if isinstance(run_filter.get("any"), list) else None
        account_state: dict[str, Any] = self._get_account_state(account_name, filter_name) if any_branches else {}
        branch_state: dict[str, Any] = {
            key: value
            for key, value in account_state.items()
            if isinstance(key, str) and key.startswith("sha256:")
        }
        branch_last_uids: dict[str, int] = {}
        single_uid = self.run_options.get("uid")
        if single_uid is not None:
            matching = [(single_uid, str(single_uid).encode("ascii"), None)]
            logger.info(f"Fetching exact UID: {single_uid}")
        else:
            if any_branches:
                persist_state = self._should_persist_state(dry_run=dry_run)
                all_branch_keys = {str(branch["branch_key"]) for branch in any_branches}
                missing_branches = [
                    branch for branch in any_branches if str(branch["branch_key"]) not in branch_state
                ]
                high_water_uid = (
                    int(self.run_options["from_uid"])
                    if self.run_options.get("from_uid") is not None
                    else max((value for value in branch_state.values() if isinstance(value, int)), default=0)
                )
                branch_last_uids = {
                    str(branch["branch_key"]): (
                        int(branch_state[str(branch["branch_key"])])
                        if isinstance(branch_state.get(str(branch["branch_key"])), int)
                        else 0
                    )
                    for branch in any_branches
                }
                logger.info(f"Filter high-water UID for {filter_name}: {high_water_uid}")
                for branch_key, last_uid in branch_last_uids.items():
                    logger.info(f"Last matching UID for branch {branch_key}: {last_uid}")

                matching_by_uid: dict[int, tuple[int, bytes, set[str] | None]] = {}

                def add_matches(
                    branch_group: list[dict[str, Any]],
                    *,
                    last_uid: int,
                    max_uid: int | None,
                    update_keys: set[str] | None,
                ) -> None:
                    if not branch_group:
                        return
                    if self._can_search_any_as_sender_or(branch_group):
                        criteria = self._imap_or(
                            [self._sender_criteria(str(branch["sender"]))[0] for branch in branch_group]
                        )
                        found = self._search_emails_by_criteria(
                            conn,
                            criteria,
                            last_uid,
                            max_uid=max_uid,
                        )
                    else:
                        found_by_uid: dict[int, bytes] = {}
                        for branch in branch_group:
                            branch_key = str(branch["branch_key"])
                            branch_floor = last_uid if update_keys is not None else branch_last_uids[branch_key]
                            branch_matches = self._search_emails(
                                conn,
                                branch.get("sender"),
                                int(branch_floor),
                                subject=branch.get("subject"),
                                since=branch.get("since_date"),
                                before=branch.get("before_date"),
                                ctx=api_ctx,
                            )
                            for uid, uid_bytes in branch_matches:
                                if max_uid is not None and uid > max_uid:
                                    continue
                                found_by_uid.setdefault(uid, uid_bytes)
                        found = sorted(found_by_uid.items(), key=lambda item: item[0])
                    for uid, uid_bytes in found:
                        existing = matching_by_uid.get(uid)
                        if existing is None:
                            matching_by_uid[uid] = (uid, uid_bytes, update_keys)
                        elif existing[2] is not None and update_keys is not None:
                            existing[2].update(update_keys)
                        else:
                            matching_by_uid[uid] = (uid, uid_bytes, None)

                try:
                    if missing_branches and self.run_options.get("from_uid") is None:
                        missing_keys = {str(branch["branch_key"]) for branch in missing_branches}
                        if high_water_uid > 0:
                            add_matches(
                                missing_branches,
                                last_uid=0,
                                max_uid=high_water_uid,
                                update_keys=missing_keys,
                            )
                        if persist_state:
                            for branch_key in missing_keys:
                                account_state[branch_key] = None
                                branch_state[branch_key] = None
                            self._save_state()
                    add_matches(
                        any_branches,
                        last_uid=high_water_uid,
                        max_uid=None,
                        update_keys=all_branch_keys,
                    )
                except Exception as exc:
                    logger.error(f"OR search failed for filter {filter_name}: {exc}")
                    conn.logout()
                    return 0

                matching = [matching_by_uid[uid] for uid in sorted(matching_by_uid)]
            else:
                last_uid = self._effective_last_uid(account_name, filter_name)
                logger.info(f"Last processed UID: {last_uid}")

                sender = run_filter.get("sender")
                subject = run_filter.get("subject")
                since = self._effective_since(account_name, filter_name, run_filter)
                before = run_filter.get("before_date")
                if not any([sender, subject, since, before]):
                    logger.error("No mail filter criteria configured for this run")
                    conn.logout()
                    return 0

                try:
                    matching = [
                        (uid, uid_bytes, None)
                        for uid, uid_bytes in self._search_emails(
                            conn,
                            sender,
                            last_uid,
                            subject=subject,
                            since=since,
                            before=before,
                            ctx=api_ctx,
                        )
                    ]
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
            for uid, uid_bytes, _branch_key in matching:
                try:
                    fetch_query = (
                        "(RFC822)"
                        if self.run_options.get("preview_body")
                        else "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])"
                    )
                    _, msg_data = self._fetch_message_data(
                        conn,
                        uid_bytes,
                        fetch_query,
                        ctx=api_ctx,
                    )
                    raw_header = self._extract_message_bytes(msg_data)
                    if raw_header is None:
                        raise ValueError("No message payload returned by IMAP FETCH")
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
                    row = {
                        "imap_uid": uid,
                        "account": account_name,
                        "subject": subject_value,
                        "sender": sender_value,
                        "timestamp": timestamp,
                        "dry_run": True,
                        "filter": filter_name,
                    }
                    if self.run_options.get("preview_body"):
                        text_body, html_body = self._message_bodies(msg)
                        body: dict[str, str] = {}
                        if text_body:
                            body["text"] = text_body
                        elif html_body:
                            body["text"] = self._html_to_text(html_body)
                        if html_body:
                            body["html"] = html_body
                        row["body"] = body
                    self.downloaded.append(row)
                except Exception as exc:
                    logger.warning(f"Dry-run header fetch failed for UID {uid}: {exc}")
            conn.logout()
            logger.info("Disconnected (dry-run)")
            return 0

        fetched_count = 0
        persist_state = self._should_persist_state(dry_run=dry_run)

        # Process each email
        sleep_seconds = self._get_sleep_seconds()

        for idx, (uid, uid_bytes, update_keys) in enumerate(matching):
            logger.info(f"Processing UID {uid}...")
            try:
                meta = self._process_email(
                    conn,
                    uid_bytes,
                    uid,
                    account_name,
                    filter_name,
                    ctx=api_ctx,
                )
                if meta:
                    self.downloaded.append(meta)
                    if persist_state:
                        if any_branches:
                            keys_to_update = update_keys or {
                                str(branch["branch_key"]) for branch in any_branches
                            }
                            for branch in any_branches:
                                matched_branch_key = str(branch["branch_key"])
                                if matched_branch_key not in keys_to_update:
                                    continue
                                if self._branch_matches_meta(branch, meta):
                                    account_state[matched_branch_key] = uid
                                    branch_state[matched_branch_key] = uid
                                else:
                                    current_branch_value = branch_state.get(matched_branch_key)
                                    if not isinstance(current_branch_value, int):
                                        account_state[matched_branch_key] = None
                                        branch_state[matched_branch_key] = None
                            self._update_last_uid(account_name, filter_name, uid)
                            self._update_last_received_date(
                                account_name,
                                filter_name,
                                meta.get("timestamp"),
                            )
                            self._save_state()
                        else:
                            self._update_last_uid(account_name, filter_name, uid)
                            self._update_last_received_date(
                                account_name,
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
        """Fetch from all selected accounts.

        Args:
            num_messages: Optional global cap for fetched messages in this run.
        """
        remaining = num_messages
        accounts = self._resolve_accounts()
        self.account_counts = {account["name"]: 0 for account in accounts}
        self.filter_counts = {}

        for run_filter in self.run_filters:
            filter_name = run_filter["name"]
            self.filter_counts[filter_name] = 0
            for account_config in accounts:
                if remaining is not None and remaining <= 0:
                    logger.info("Reached --num cap; stopping account scan")
                    break

                fetched = self.fetch_account(
                    account_config,
                    run_filter,
                    max_messages=remaining,
                    dry_run=dry_run,
                )
                self.account_counts[account_config["name"]] += fetched
                self.filter_counts[filter_name] += fetched
                if remaining is not None:
                    remaining -= fetched if not dry_run else 0

            if remaining is not None and remaining <= 0:
                break

        return self.downloaded


def main() -> None:
    """Run the Yandex Mail fetcher command-line interface."""
    parser = argparse.ArgumentParser(description="Fetch emails from Yandex Mail")
    parser.add_argument(
        "--num",
        type=int,
        default=None,
        help="Maximum number of new messages to fetch in this run (global cap across accounts)",
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
        "--account",
        help="Run only for the named token-backed account alias",
    )
    parser.add_argument(
        "--from-uid",
        type=int,
        help="Start this run from the given UID floor without persisting state",
    )
    parser.add_argument(
        "--uid",
        type=int,
        help="Fetch exactly one UID without filter search logic or state updates",
    )
    parser.add_argument(
        "--preview-body",
        action="store_true",
        help="In dry-run mode, fetch message bodies into the JSON preview without writing incoming/",
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
        help="Explicit Yandex data directory override for non-CWD execution",
    )
    args = parser.parse_args()

    if args.num is not None and args.num <= 0:
        parser.error("--num must be a positive integer")
    if args.from_uid is not None and args.from_uid <= 0:
        parser.error("--from-uid must be a positive integer")
    if args.uid is not None and args.uid <= 0:
        parser.error("--uid must be a positive integer")
    if args.uid is not None and args.from_uid is not None:
        parser.error("--uid cannot be combined with --from-uid")
    if args.preview_body and not args.dry_run:
        parser.error("--preview-body requires --dry-run")

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
            account_name=args.account,
            from_uid=args.from_uid,
            uid=args.uid,
            no_persist=args.no_persist or args.uid is not None,
            preview_body=args.preview_body,
        )
        results = fetcher.fetch_all(num_messages=args.num, dry_run=args.dry_run)
    except ValueError as exc:
        parser.error(str(exc))

    pending_rows = []
    if args.dry_run:
        pending_rows = []
        for item in results:
            row = {
                "uid": item.get("imap_uid"),
                "account": item.get("account"),
                "sender": item.get("sender", ""),
                "subject": item.get("subject", ""),
                "timestamp": item.get("timestamp", ""),
                "filter": item.get("filter", ""),
            }
            if "body" in item:
                row["body"] = item.get("body", {})
            pending_rows.append(row)

    response = {
        "dry_run": bool(args.dry_run),
        "filter": fetcher.active_filter["name"] if fetcher.active_filter else None,
        "filters": [item["name"] for item in fetcher.run_filters],
        "persist_state": fetcher._should_persist_state(dry_run=args.dry_run),
        "fetched_total": 0 if args.dry_run else len(results),
        "pending_total": len(pending_rows) if args.dry_run else 0,
        "pending": pending_rows if args.dry_run else [],
        "preview_body": bool(args.preview_body) if args.dry_run else False,
        "accounts": fetcher.account_counts,
        "filter_counts": fetcher.filter_counts,
    }

    if args.dry_run:
        pending_json = json.dumps(pending_rows, ensure_ascii=False, indent=2)
        threshold = fetcher._get_output_max_inline_symbols()
        if len(pending_json) > threshold:
            full_payload = dict(response)
            full_payload["pending"] = pending_rows
            output_path = fetcher._spill_payload_to_file(full_payload, prefix="mail_dry_run")
            response["pending"] = []
            response["output_file"] = str(output_path)
            response["output_spilled"] = True
            response["inline_threshold_symbols"] = threshold
            response["output_notice"] = (
                "Copy this file if you need to keep it. The next spilled run replaces "
                "the previous spill artifact."
            )

    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
