#!/usr/bin/env python3
"""
Telemost meeting processor — orchestrator.

Scans `incoming/` for unprocessed email directories, enriches Telemost emails
with meeting-specific metadata, groups them by meeting UID, merges "summary"
(transcript) and "recording" (video/audio) data, and outputs structured
meeting documents.

Data flow:
    {data_dir}/incoming/{date}_{mailbox}_uid{N}/meta.json
    → enrich: classify, extract meeting_uid/title/links
    → group by meeting_uid
    → merge metadata from both email types
    → transform transcript (UTC diarization)
    → output to {data_dir}/meetings/{YYYY-MM}/{YYYY-MM-DD_HH-MM}_{mailbox}_{MEETING_UID}/
    → archive processed dirs
"""

import argparse
import json
import logging
import re
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.config import load_runtime_context
from process_transcript import transform_transcript, format_utc, parse_reference_timestamp

logger = logging.getLogger("telemost")

# ── Business logic moved from mail ─────────────────────────────────────

# Telemost meeting UID pattern in email body
TELEMOST_UID_RE = re.compile(r'https://telemost\.yandex\.ru/j/(\d+)')

# Meeting title in "Запись встречи «Title» от DD.MM.YYYY"
MEETING_TITLE_RE = re.compile(r'\u00ab(.+?)\u00bb')

# yadi.sk links for video/audio
YADISK_LINK_RE = re.compile(r'https://yadi\.sk/[a-zA-Z0-9/_-]+')

TELEMOST_SENDER = "keeper@telemost.yandex.ru"


MSK = timezone(timedelta(hours=3))

MEETING_START_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s+в\s+(\d{1,2}):(\d{2})")


def extract_meeting_start_local(body_text: str) -> str | None:
    """Extract meeting local start timestamp from plain-text body.

    Supports phrases like:
      - "Запись началась 13.02.2026 в 19:08"
      - "Конспектирование началось 13.02.2026 в 19:08 (MSK)"
    Returns ISO-like local timestamp: YYYY-MM-DDTHH:MM
    """
    m = MEETING_START_RE.search(body_text)
    if not m:
        return None
    day, month, year, hour, minute = (int(x) for x in m.groups())
    return datetime(year, month, day, hour, minute).strftime("%Y-%m-%dT%H:%M")


def classify_email(subject: str) -> str:
    """Classify email type from subject line.

    Returns: 'summary', 'recording', or 'unknown'
    """
    if subject.startswith("Конспект встречи"):
        return "summary"
    if subject.startswith("Запись встречи"):
        return "recording"
    return "unknown"


def extract_meeting_uid(body_text: str) -> str | None:
    """Extract Telemost meeting UID from email plain text body.

    Looks for https://telemost.yandex.ru/j/{UID} pattern.
    """
    match = TELEMOST_UID_RE.search(body_text)
    return match.group(1) if match else None


def extract_meeting_title(subject: str) -> str | None:
    """Extract meeting title from 'Запись встречи «Title» от ...' subject."""
    match = MEETING_TITLE_RE.search(subject)
    return match.group(1) if match else None


def extract_media_links(body_text: str) -> list[str]:
    """Extract yadi.sk links from email plain text body."""
    return YADISK_LINK_RE.findall(body_text)


# ── Meeting output naming helpers ──────────────────────────────────────────────

INCOMING_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_(?P<tag>[a-zA-Z0-9_-]+)_uid\d+$")


def _parse_iso_timestamp(raw_value: str | None) -> datetime | None:
    """Parse ISO-like timestamps commonly found in meta.json."""
    if not raw_value:
        return None
    value = str(raw_value).strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _normalize_tag(raw_value: str | None) -> str:
    """Normalize mailbox tag for filesystem-safe directory naming."""
    if not raw_value:
        return "unknown"
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", str(raw_value).lower()).strip("-")
    return cleaned or "unknown"


def infer_mailbox_tag(meeting_data: dict) -> str:
    """Infer mailbox tag from source email metadata."""
    for src in meeting_data.get("source_emails", []):
        mailbox = src.get("mailbox")
        if mailbox:
            return _normalize_tag(mailbox)

        dir_name = src.get("dir_name")
        if not dir_name:
            continue
        match = INCOMING_DIR_RE.match(dir_name)
        if match:
            return _normalize_tag(match.group("tag"))
    return "unknown"


def resolve_meeting_datetime(meeting_data: dict) -> datetime:
    """Resolve meeting start datetime in local time for path naming."""
    # Prefer explicit local meeting start parsed from email_body.txt.
    dt = _parse_iso_timestamp(meeting_data.get("meeting_start_local"))
    if dt:
        return dt

    for src in meeting_data.get("source_emails", []):
        dt = _parse_iso_timestamp(src.get("meeting_start_local"))
        if dt:
            return dt

    # Fallback to explicit reference UTC stored in meeting metadata.
    dt = _parse_iso_timestamp(meeting_data.get("reference_utc"))
    if dt:
        return dt.astimezone(MSK).replace(tzinfo=None) if dt.tzinfo else dt

    # If transcript exists, derive canonical meeting start from its header.
    transcript_file = meeting_data.get("transcript_file")
    if transcript_file:
        transcript_path = Path(transcript_file)
        if transcript_path.exists():
            first_line = transcript_path.read_text(encoding="utf-8").splitlines()
            if first_line:
                ref_utc = parse_reference_timestamp(first_line[0])
                if ref_utc:
                    return ref_utc.astimezone(MSK).replace(tzinfo=None)

    dt = _parse_iso_timestamp(meeting_data.get("date"))
    if dt:
        return dt.astimezone(MSK).replace(tzinfo=None) if dt.tzinfo else dt

    for src in meeting_data.get("source_emails", []):
        dt = _parse_iso_timestamp(src.get("timestamp"))
        if dt:
            return dt.astimezone(MSK).replace(tzinfo=None) if dt.tzinfo else dt

    return datetime(1970, 1, 1, 0, 0, 0)


def build_meeting_output_path(meeting_data: dict, output_base: Path) -> Path:
    """Build output path: YYYY-MM/YYYY-MM-DD_HH-MM_{mailbox}_{meeting_uid}."""
    dt = resolve_meeting_datetime(meeting_data)
    tag = infer_mailbox_tag(meeting_data)
    meeting_uid = meeting_data.get("meeting_uid") or "unknown"

    month_bucket = dt.strftime("%Y-%m")
    date_part = dt.strftime("%Y-%m-%d")
    local_time_part = dt.strftime("%H-%M")
    dir_name = f"{date_part}_{local_time_part}_{tag}_{meeting_uid}"
    return output_base / month_bucket / dir_name


def resolve_same_day_output_dir(meeting_data: dict, output_base: Path) -> Path:
    """Resolve output dir by same-day wildcard with single-candidate invariant.

    Pattern: YYYY-MM/YYYY-MM-DD_*-*_{mailbox}_{meeting_uid}
    - 0 candidates: create a new standard path from incoming event time
    - 1 candidate: append to that existing path
    - >1 candidates: fail fast (data integrity error)
    """
    dt = resolve_meeting_datetime(meeting_data)
    tag = infer_mailbox_tag(meeting_data)
    meeting_uid = meeting_data.get("meeting_uid") or "unknown"

    month_bucket = dt.strftime("%Y-%m")
    date_part = dt.strftime("%Y-%m-%d")
    month_dir = output_base / month_bucket
    pattern = f"{date_part}_*-*_{tag}_{meeting_uid}"

    candidates = sorted(
        p for p in month_dir.glob(pattern)
        if p.is_dir()
    ) if month_dir.exists() else []

    if len(candidates) == 0:
        return build_meeting_output_path(meeting_data, output_base)
    if len(candidates) == 1:
        return candidates[0]

    candidate_list = ", ".join(str(p) for p in candidates)
    raise RuntimeError(
        f"Multiple same-day meeting directories found for meeting_uid={meeting_uid} "
        f"mailbox={tag} date={date_part}: {candidate_list}"
    )


# ── Enrichment phase ──────────────────────────────────────────────────────────

def enrich_incoming(incoming_dir: Path, sender_filter: str = TELEMOST_SENDER) -> int:
    """Scan incoming/ and enrich Telemost emails with meeting-specific metadata.

    For each email directory with meta.json:
    1. Check if sender matches (only Telemost emails)
    2. Classify subject -> 'summary' or 'recording'
    3. Extract meeting_uid from plain text body
    4. Extract meeting_title from subject (for 'recording' type)
    5. Extract yadi.sk media links from plain text body
    6. Extract meeting_start_local from plain text body
    7. Read YandexGPT summary from email_body.txt (for 'summary' type)
    8. Update meta.json with enriched fields

    Returns count of enriched emails.
    """
    if not incoming_dir.exists():
        return 0

    enriched = 0
    for entry in sorted(incoming_dir.iterdir()):
        if not entry.is_dir():
            continue
        meta_path = entry / "meta.json"
        if not meta_path.exists():
            continue

        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        # Skip already-enriched emails
        if "email_type" in meta:
            continue

        # Only process emails from Telemost
        sender = meta.get("sender", "")
        if sender_filter not in sender:
            continue

        subject = meta.get("subject", "")

        # Classify
        email_type = classify_email(subject)
        meta["email_type"] = email_type

        # Read plain text body for extraction
        txt_path = entry / "email_body.txt"
        text_body = txt_path.read_text(encoding="utf-8") if txt_path.exists() else ""

        # Extract meeting UID
        meta["meeting_uid"] = extract_meeting_uid(text_body)

        # Extract meeting title (only from recording subjects)
        meta["meeting_title"] = None
        if email_type == "recording":
            meta["meeting_title"] = extract_meeting_title(subject)

        # Extract media links
        meta["media_links"] = extract_media_links(text_body)

        # Parse local meeting start from body text phrase.
        meta["meeting_start_local"] = extract_meeting_start_local(text_body)

        # Save YandexGPT summary (from 'summary' email body)
        meta["telemost_summary"] = None
        if email_type == "summary" and txt_path.exists():
            meta["telemost_summary"] = text_body

        # Write enriched meta.json
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        enriched += 1
        logger.info(f"Enriched {entry.name}: {email_type} meeting_uid={meta['meeting_uid']}")

    return enriched


# ── Pipeline functions ────────────────────────────────────────────────────────

def scan_incoming(incoming_dir: Path) -> list[dict]:
    """Find enriched Telemost email directories in incoming/.

    Only returns emails that have been enriched (have email_type field).
    Each dir must contain a meta.json to be considered valid.
    Returns list of metadata dicts (with 'dir_path' added).
    """
    results = []
    if not incoming_dir.exists():
        return results

    for entry in sorted(incoming_dir.iterdir()):
        if not entry.is_dir():
            continue
        meta_path = entry / "meta.json"
        if not meta_path.exists():
            logger.warning(f"Skipping {entry.name}: no meta.json")
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        # Only include enriched Telemost emails
        if "email_type" not in meta:
            continue
        meta["dir_path"] = str(entry)
        results.append(meta)

    return results


def group_by_meeting_uid(emails: list[dict]) -> dict[str, list[dict]]:
    """Group email metadata by meeting_uid.

    Emails without a meeting_uid get grouped under their dir_name
    (treated as standalone meetings).
    """
    groups = {}
    for em in emails:
        key = em.get("meeting_uid") or em.get("dir_name", "unknown")
        groups.setdefault(key, []).append(em)
    return groups


def merge_meeting_data(emails: list[dict]) -> dict:
    """Merge data from 'summary' and 'recording' emails into a single meeting record.

    Returns merged metadata dict.
    """
    merged = {
        "meeting_uid": None,
        "meeting_title": None,
        "date": None,
        "meeting_start_local": None,
        "participants": [],
        "summary": None,
        "summary_file": None,
        "telemost_summary": None,
        "transcript_file": None,
        "media_links": [],
        "source_emails": [],
    }

    for em in emails:
        email_type = em.get("email_type", "unknown")
        dir_path = Path(em["dir_path"])

        merged["meeting_uid"] = merged["meeting_uid"] or em.get("meeting_uid")
        merged["date"] = merged["date"] or em.get("timestamp", em.get("date"))
        merged["meeting_start_local"] = merged["meeting_start_local"] or em.get("meeting_start_local")
        merged["source_emails"].append({
            "imap_uid": em.get("imap_uid"),
            "email_type": email_type,
            "subject": em.get("subject"),
            "mailbox": em.get("mailbox"),
            "timestamp": em.get("timestamp"),
            "meeting_start_local": em.get("meeting_start_local"),
            "dir_name": em.get("dir_name"),
        })

        if email_type == "summary":
            # Find transcript .txt file (newest by mtime)
            txt_files = sorted(dir_path.glob("*.txt"), key=lambda p: p.stat().st_mtime)
            txt_files = [f for f in txt_files if f.name != "email_body.txt"]
            if txt_files:
                merged["transcript_file"] = str(txt_files[-1])

            body_path = dir_path / "email_body.txt"
            if body_path.exists():
                merged["summary_file"] = str(body_path)

            # Preserve telemost_summary from enrichment if present.
            if em.get("telemost_summary"):
                merged["telemost_summary"] = em["telemost_summary"]
                merged["summary"] = em["telemost_summary"]
            elif body_path.exists():
                merged["summary"] = body_path.read_text(encoding="utf-8")

        elif email_type == "recording":
            # Meeting title from subject
            if em.get("meeting_title"):
                merged["meeting_title"] = em["meeting_title"]

            # Media links
            links = em.get("media_links", [])
            merged["media_links"].extend(links)

    return merged


def _is_defined(value) -> bool:
    """Return True for meaningful values that should override persisted metadata."""
    return value not in (None, "", [], {})


def _merge_existing_meta(existing: dict, fresh: dict) -> dict:
    """Merge fresh meeting metadata into existing meta without destructive overwrites."""
    merged = dict(existing or {})

    scalar_keys = ("meeting_uid", "title", "reference_utc", "telemost_summary")
    for key in scalar_keys:
        if _is_defined(fresh.get(key)):
            merged[key] = fresh[key]
        elif key not in merged:
            merged[key] = fresh.get(key)

    # Keep participant names unique, preserving order.
    seen_names = set()
    participants = []
    for part in (existing.get("participants", []) if isinstance(existing, dict) else []):
        if isinstance(part, dict):
            name = part.get("name")
            if name and name not in seen_names:
                seen_names.add(name)
                participants.append({"name": name})
    for part in fresh.get("participants", []):
        if isinstance(part, dict):
            name = part.get("name")
            if name and name not in seen_names:
                seen_names.add(name)
                participants.append({"name": name})
    merged["participants"] = participants

    # Keep media links unique, preserving order.
    seen_links = set()
    links = []
    for link in (existing.get("media_links", []) if isinstance(existing, dict) else []):
        if link and link not in seen_links:
            seen_links.add(link)
            links.append(link)
    for link in fresh.get("media_links", []):
        if link and link not in seen_links:
            seen_links.add(link)
            links.append(link)
    merged["media_links"] = links

    # Merge source emails by imap_uid first, then by dir_name fallback.
    existing_sources = existing.get("source_emails", []) if isinstance(existing, dict) else []
    fresh_sources = fresh.get("source_emails", [])
    seen_source_keys = set()
    source_emails = []
    for src in list(existing_sources) + list(fresh_sources):
        if not isinstance(src, dict):
            continue
        key = src.get("imap_uid")
        if key is None:
            key = f"dir:{src.get('dir_name')}"
        if key in seen_source_keys:
            continue
        seen_source_keys.add(key)
        source_emails.append(src)
    merged["source_emails"] = source_emails

    merged["processed_at"] = fresh.get("processed_at") or datetime.now().isoformat()

    # Partial is recomputed from merged state, not from only fresh batch.
    merged["partial"] = not (bool(merged.get("reference_utc")) and bool(merged.get("media_links")))

    return merged


def _append_section(path: Path, separator: str, body: str) -> None:
    """Append a separated section into an output text file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = "\n\n" if path.exists() and path.stat().st_size > 0 else ""
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{prefix}{separator}\n")
        if body:
            f.write(body.rstrip() + "\n")


def process_meeting(
    meeting_data: dict,
    output_base: Path,
) -> dict | None:
    """Process a single meeting: transform transcript, write outputs.

    Returns result dict or None on failure.
    """
    meeting_uid = meeting_data["meeting_uid"] or "unknown"
    title = meeting_data["meeting_title"]

    try:
        meeting_dir = resolve_same_day_output_dir(meeting_data, output_base)
    except RuntimeError as exc:
        logger.error(str(exc))
        return None
    meeting_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "meeting_uid": meeting_uid,
        "meeting_dir": str(meeting_dir),
        "has_transcript": False,
        "has_summary": False,
        "has_recording_links": False,
        "speakers": [],
        "reference_utc": None,
    }

    source_email = meeting_data.get("source_emails", [{}])[0] if meeting_data.get("source_emails") else {}
    source_uid = source_email.get("imap_uid")
    source_type = source_email.get("email_type", "unknown")
    source_start = source_email.get("meeting_start_local") or meeting_data.get("meeting_start_local") or "unknown"

    # Process transcript (if 'summary' email was received), append into single transcript.txt
    if meeting_data.get("transcript_file"):
        transcript_path = Path(meeting_data["transcript_file"])
        if transcript_path.exists():
            raw_text = transcript_path.read_text(encoding="utf-8")
            transformed, ref_utc, speakers = transform_transcript(raw_text)
            separator = (
                f"=== imap_uid={source_uid} type={source_type} "
                f"start_local={source_start} ==="
            )
            _append_section(meeting_dir / "transcript.txt", separator, transformed)
            result["has_transcript"] = True
            result["speakers"] = speakers
            result["reference_utc"] = format_utc(ref_utc) if ref_utc else None

    # Save summary by appending into single summary.txt.
    summary_file = meeting_data.get("summary_file")
    if summary_file:
        src = Path(summary_file)
        if src.exists():
            summary_text = src.read_text(encoding="utf-8")
            separator = f"=== imap_uid={source_uid} type={source_type} ==="
            _append_section(meeting_dir / "summary.txt", separator, summary_text)
            result["has_summary"] = True
    elif meeting_data.get("summary"):
        separator = f"=== imap_uid={source_uid} type={source_type} ==="
        _append_section(meeting_dir / "summary.txt", separator, meeting_data["summary"])
        result["has_summary"] = True

    # Build meeting metadata
    fresh_meta = {
        "meeting_uid": meeting_uid,
        "title": title,
        "reference_utc": result["reference_utc"],
        "telemost_summary": meeting_data.get("telemost_summary"),
        "participants": [{"name": s} for s in result["speakers"]],
        "media_links": meeting_data.get("media_links", []),
        "source_emails": meeting_data.get("source_emails", []),
        "processed_at": datetime.now().isoformat(),
        "partial": not (meeting_data.get("transcript_file") and meeting_data.get("media_links")),
    }

    meta_path = meeting_dir / "meeting.meta.json"
    existing_meta = {}
    if meta_path.exists():
        try:
            existing_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing_meta = {}

    meta = _merge_existing_meta(existing_meta, fresh_meta)

    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    result["has_recording_links"] = bool(meeting_data.get("media_links"))

    return result


def archive_dirs(email_dirs: list[str], archive_base: Path):
    """Move processed incoming dirs to archive."""
    archive_base.mkdir(parents=True, exist_ok=True)
    for dir_path_str in email_dirs:
        src = Path(dir_path_str)
        if src.exists():
            dst = archive_base / src.name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.move(str(src), str(dst))
            logger.info(f"Archived: {src.name}")


def download_recordings(meeting_data: dict, meeting_dir: Path) -> list[dict]:
    """Download yadi.sk recordings via disk skill (optional integration).

    Uses the mailbox/account name from meeting metadata to resolve the
    correct token file (data/auth/{account}.token).

    Requires disk skill to be available (sys.path or installed).
    Returns list of download result dicts, or empty list on failure.
    """
    links = meeting_data.get("media_links", [])
    if not links:
        return []

    try:
        import sys

        # Try to find disk scripts (sibling skill directory)
        disk_scripts = Path(__file__).resolve().parent.parent.parent / "disk" / "scripts"
        if disk_scripts.exists() and str(disk_scripts) not in sys.path:
            sys.path.insert(0, str(disk_scripts))

        from download import YandexDisk
    except ImportError:
        logger.warning("disk skill not available — skipping recording downloads")
        return []

    account = next(
        (src.get("mailbox") for src in meeting_data.get("source_emails", []) if src.get("mailbox")),
        None,
    )

    disk = YandexDisk(account=account)
    recordings_dir = meeting_dir / "recordings"
    results = []

    for link in links:
        try:
            result = disk.download_with_meta(link, output_dir=str(recordings_dir))
            results.append(result)
            logger.info(f"Downloaded recording: {result['name']} ({result['size']} bytes)")
        except Exception as e:
            logger.warning(f"Failed to download {link}: {e}")

    return results


def report_result(
    result: dict,
    meeting_data: dict,
    verbose: bool = False,
    data_dir: Path | None = None,
) -> str:
    """Output processing result summary for operators.

    Non-verbose mode prints minimal status line.
    """
    title = meeting_data.get("meeting_title") or "Untitled"

    if not verbose:
        meeting_dir = Path(result["meeting_dir"])
        if data_dir is not None:
            try:
                meeting_dir = meeting_dir.relative_to(data_dir)
            except ValueError:
                pass
        return str(meeting_dir)

    summary_preview = ""
    if meeting_data.get("summary"):
        lines = meeting_data["summary"].splitlines()
        topic_idx = None
        for idx, line in enumerate(lines):
            if re.match(r"^Тема\s+\d+", line.strip()):
                topic_idx = idx
                break
        if topic_idx is not None:
            lines = lines[topic_idx:]
        summary_preview = "\n".join(lines).strip()[:250]

    parts = [
        f"Meeting: {title}",
        f"UID: {result['meeting_uid']}",
        f"Reference UTC: {result.get('reference_utc', 'N/A')}",
        f"Speakers: {', '.join(result.get('speakers', []))}",
        f"Transcript: {'yes' if result['has_transcript'] else 'no'}",
        f"Summary: {'yes' if result['has_summary'] else 'no'}",
        f"Recording links: {'yes' if result['has_recording_links'] else 'no'}",
        f"Output: {result['meeting_dir']}",
    ]
    if summary_preview:
        parts.append(f"\nSummary preview:\n{summary_preview}")
    if meeting_data.get("media_links"):
        parts.append("\nMedia links:\n" + "\n".join(f"  {l}" for l in meeting_data["media_links"]))

    message = "\n".join(parts)
    print(message)
    return message


def main():
    parser = argparse.ArgumentParser(
        description="Process Telemost meetings from incoming/ directory"
    )
    parser.add_argument(
        "--incoming", default=None,
        help="Override incoming directory path"
    )
    parser.add_argument(
        "--output", default=None,
        help="Override output directory path"
    )
    parser.add_argument(
        "--archive", default=None,
        help="Override archive directory path"
    )
    parser.add_argument(
        "--no-archive", action="store_true",
        help="Do not move processed dirs to archive"
    )
    parser.add_argument(
        "--download-recordings", action="store_true",
        help="Download yadi.sk recordings via disk skill"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--data-dir", default=None,
        help="Explicit Yandex data directory override for non-workspace execution"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    runtime = load_runtime_context(
        __file__,
        data_dir_override=args.data_dir,
        require_agent_config=True,
        require_external_data_dir=True,
    )
    data_dir = runtime.data_dir

    incoming_dir = Path(args.incoming) if args.incoming else data_dir / "incoming"
    output_base = Path(args.output) if args.output else data_dir / "meetings"
    archive_base = Path(args.archive) if args.archive else data_dir / "archive"

    # Phase 1: Enrich incoming emails with Telemost-specific metadata
    enriched_count = enrich_incoming(incoming_dir)
    if enriched_count and args.verbose:
        logger.info(f"Enriched {enriched_count} email(s)")

    # Phase 2: Scan enriched emails
    emails = scan_incoming(incoming_dir)
    if not emails:
        print(json.dumps({"processed": []}, ensure_ascii=False, indent=2))
        return

    if args.verbose:
        logger.info(f"Found {len(emails)} enriched email(s) in incoming/")

    # Group by meeting UID
    groups = group_by_meeting_uid(emails)
    if args.verbose:
        logger.info(f"Grouped into {len(groups)} meeting(s)")

    report_items = []

    # Process each meeting email-by-email in natural imap_uid order.
    for meeting_uid, group_emails in groups.items():
        if args.verbose:
            logger.info(f"Processing meeting {meeting_uid} ({len(group_emails)} email(s))")
        sorted_emails = sorted(
            group_emails,
            key=lambda em: int(em.get("imap_uid")) if str(em.get("imap_uid", "")).isdigit() else 10**18,
        )
        processed_dirs = []

        for em in sorted_emails:
            meeting_data = merge_meeting_data([em])
            result = process_meeting(meeting_data, output_base)

            if result:
                # Optionally download recordings for this email event.
                if args.download_recordings and meeting_data.get("media_links"):
                    meeting_dir = Path(result["meeting_dir"])
                    dl_results = download_recordings(meeting_data, meeting_dir)
                    if dl_results:
                        result["downloaded_recordings"] = len(dl_results)

                report_value = report_result(
                    result,
                    meeting_data,
                    verbose=args.verbose,
                    data_dir=data_dir,
                )
                if not args.verbose:
                    report_items.append(report_value)
                processed_dirs.append(em["dir_path"])
            else:
                logger.error(f"Failed to process meeting {meeting_uid} email {em.get('imap_uid')}")

        # Archive only after all events in this meeting were handled.
        if not args.no_archive and processed_dirs:
            archive_dirs(processed_dirs, archive_base)

    if args.verbose:
        print(f"\nDone. Processed {len(groups)} meeting(s).")
    else:
        print(json.dumps({"processed": report_items}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
