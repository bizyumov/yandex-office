#!/usr/bin/env python3
"""
Telemost meeting processor — orchestrator.

Scans `incoming/` for unprocessed email directories, groups them by
meeting UID, merges "Конспект" (transcript) and "Запись" (recording)
data, and outputs structured meeting documents.

Data flow:
    incoming/{date}_{mailbox}_uid{N}/meta.json  →  group by meeting_uid
    → merge metadata from both email types
    → transform transcript (UTC diarization)
    → output to documents/meetings/{MEETING_UID}/
    → archive processed dirs
"""

import json
import shutil
import logging
import argparse
from pathlib import Path
from datetime import datetime

from process_transcript import transform_transcript, format_utc

logger = logging.getLogger("yandex-telemost")


def scan_incoming(incoming_dir: Path) -> list[dict]:
    """Find unprocessed email directories in incoming/.

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
    """Merge data from "Конспект" and "Запись" emails into a single meeting record.

    Returns merged metadata dict.
    """
    merged = {
        "meeting_uid": None,
        "meeting_title": None,
        "date": None,
        "participants": [],
        "summary": None,
        "transcript_file": None,
        "video_url": None,
        "audio_url": None,
        "media_links": [],
        "source_emails": [],
    }

    for em in emails:
        email_type = em.get("email_type", "unknown")
        dir_path = Path(em["dir_path"])

        merged["meeting_uid"] = merged["meeting_uid"] or em.get("meeting_uid")
        merged["date"] = merged["date"] or em.get("date")
        merged["source_emails"].append({
            "imap_uid": em.get("imap_uid"),
            "email_type": email_type,
            "subject": em.get("subject"),
            "dir_name": em.get("dir_name"),
        })

        if email_type == "konspekt":
            # Find transcript .txt file (newest by mtime)
            txt_files = sorted(dir_path.glob("*.txt"), key=lambda p: p.stat().st_mtime)
            txt_files = [f for f in txt_files if f.name != "email_body.txt"]
            if txt_files:
                merged["transcript_file"] = str(txt_files[-1])

            # Email body = YandexGPT summary
            body_path = dir_path / "email_body.txt"
            if body_path.exists():
                merged["summary"] = body_path.read_text(encoding="utf-8")

        elif email_type == "zapis":
            # Meeting title from subject
            if em.get("meeting_title"):
                merged["meeting_title"] = em["meeting_title"]

            # Media links
            links = em.get("media_links", [])
            merged["media_links"].extend(links)

            # Try to identify video vs audio from links
            for link in links:
                if not merged["video_url"]:
                    merged["video_url"] = link
                elif not merged["audio_url"]:
                    merged["audio_url"] = link

    return merged


def process_meeting(
    meeting_data: dict,
    output_base: Path,
) -> dict | None:
    """Process a single meeting: transform transcript, write outputs.

    Returns result dict or None on failure.
    """
    meeting_uid = meeting_data["meeting_uid"] or "unknown"
    date = meeting_data["date"] or "unknown"
    title = meeting_data["meeting_title"]

    # Output directory
    meeting_dir = output_base / meeting_uid
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

    # Process transcript (if "Конспект" was received)
    if meeting_data.get("transcript_file"):
        transcript_path = Path(meeting_data["transcript_file"])
        if transcript_path.exists():
            raw_text = transcript_path.read_text(encoding="utf-8")
            transformed, ref_utc, speakers = transform_transcript(raw_text)

            (meeting_dir / "transcript.txt").write_text(transformed, encoding="utf-8")
            result["has_transcript"] = True
            result["speakers"] = speakers
            result["reference_utc"] = format_utc(ref_utc) if ref_utc else None

    # Save summary (YandexGPT auto-summary from "Конспект" body)
    if meeting_data.get("summary"):
        (meeting_dir / "summary.txt").write_text(meeting_data["summary"], encoding="utf-8")
        result["has_summary"] = True

    # Build meeting metadata
    meta = {
        "meeting_uid": meeting_uid,
        "title": title,
        "date": date,
        "reference_utc": result["reference_utc"],
        "participants": [{"name": s} for s in result["speakers"]],
        "video_url": meeting_data.get("video_url"),
        "audio_url": meeting_data.get("audio_url"),
        "media_links": meeting_data.get("media_links", []),
        "source_emails": meeting_data.get("source_emails", []),
        "processed_at": datetime.now().isoformat(),
        "partial": not (meeting_data.get("transcript_file") and meeting_data.get("media_links")),
    }

    (meeting_dir / "meeting.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

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
    """Download yadi.sk recordings via yandex-disk (optional integration).

    Requires yandex-disk skill to be available (sys.path or installed).
    Returns list of download result dicts, or empty list on failure.
    """
    links = meeting_data.get("media_links", [])
    if not links:
        return []

    try:
        import sys
        import os

        # Try to find yandex-disk scripts (sibling skill directory)
        disk_scripts = Path(__file__).resolve().parent.parent.parent / "yandex-disk" / "scripts"
        if disk_scripts.exists() and str(disk_scripts) not in sys.path:
            sys.path.insert(0, str(disk_scripts))

        from download import YandexDisk
    except ImportError:
        logger.warning("yandex-disk not available — skipping recording downloads")
        return []

    disk = YandexDisk()  # Uses YANDEX_DISK_TOKEN env var
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


def report_result(result: dict, meeting_data: dict) -> str:
    """Output processing result summary for LLM consumers."""
    title = meeting_data.get("meeting_title") or "Untitled"
    summary_preview = ""
    if meeting_data.get("summary"):
        summary_preview = meeting_data["summary"][:500]

    parts = [
        f"Meeting: {title}",
        f"UID: {result['meeting_uid']}",
        f"Date: {meeting_data.get('date', 'unknown')}",
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
        parts.append(f"\nMedia links:\n" + "\n".join(f"  {l}" for l in meeting_data["media_links"]))

    message = "\n".join(parts)
    print(message)
    return message


def main():
    parser = argparse.ArgumentParser(
        description="Process Telemost meetings from incoming/ directory"
    )
    parser.add_argument(
        "--incoming", default="incoming",
        help="Path to incoming directory (default: incoming)"
    )
    parser.add_argument(
        "--output", default="documents/meetings",
        help="Path to output directory (default: documents/meetings)"
    )
    parser.add_argument(
        "--archive", default="archive",
        help="Path to archive directory (default: archive)"
    )
    parser.add_argument(
        "--no-archive", action="store_true",
        help="Do not move processed dirs to archive"
    )
    parser.add_argument(
        "--download-recordings", action="store_true",
        help="Download yadi.sk recordings via yandex-disk skill"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    incoming_dir = Path(args.incoming)
    output_base = Path(args.output)
    archive_base = Path(args.archive)

    # Scan
    emails = scan_incoming(incoming_dir)
    if not emails:
        print("No unprocessed emails in incoming/")
        return

    logger.info(f"Found {len(emails)} email(s) in incoming/")

    # Group by meeting UID
    groups = group_by_meeting_uid(emails)
    logger.info(f"Grouped into {len(groups)} meeting(s)")

    # Process each meeting
    for meeting_uid, group_emails in groups.items():
        logger.info(f"Processing meeting {meeting_uid} ({len(group_emails)} email(s))")

        meeting_data = merge_meeting_data(group_emails)
        result = process_meeting(meeting_data, output_base)

        if result:
            # Optionally download recordings
            if args.download_recordings and meeting_data.get("media_links"):
                meeting_dir = Path(result["meeting_dir"])
                dl_results = download_recordings(meeting_data, meeting_dir)
                if dl_results:
                    result["downloaded_recordings"] = len(dl_results)

            report_result(result, meeting_data)

            # Archive processed dirs
            if not args.no_archive:
                dirs_to_archive = [em["dir_path"] for em in group_emails]
                archive_dirs(dirs_to_archive, archive_base)
        else:
            logger.error(f"Failed to process meeting {meeting_uid}")

    print(f"\nDone. Processed {len(groups)} meeting(s).")


if __name__ == "__main__":
    main()
