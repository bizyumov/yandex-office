#!/usr/bin/env python3
"""Rename existing Telemost meeting directories to the canonical layout.

Target layout:
    {data_dir}/meetings/{YYYY-MM}/{YYYY-MM-DD_HH-MM}_{mailbox}_{MEETING_UID}/
"""

import argparse
import logging
import shutil
from pathlib import Path

import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.config import load_runtime_context
from process_meeting import build_meeting_output_path

logger = logging.getLogger("telemost-migrate")


def iter_meeting_dirs(meetings_root: Path) -> list[Path]:
    """Find all directories containing meeting.meta.json."""
    if not meetings_root.exists():
        return []
    dirs = []
    for meta_path in meetings_root.rglob("meeting.meta.json"):
        parent = meta_path.parent
        if parent.is_dir():
            dirs.append(parent)
    # Shortest paths first gives stable logs and avoids duplicate handling.
    return sorted(set(dirs), key=lambda p: (len(p.parts), str(p)))


def target_for_existing_dir(src_dir: Path, meetings_root: Path) -> Path:
    meta_path = src_dir / "meeting.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meeting_data = {
        "meeting_uid": meta.get("meeting_uid"),
        "date": meta.get("date"),
        "reference_utc": meta.get("reference_utc"),
        "source_emails": meta.get("source_emails", []),
    }
    return build_meeting_output_path(meeting_data, meetings_root)


def migrate_meeting_dirs(meetings_root: Path, dry_run: bool = False) -> tuple[int, int, int]:
    """Migrate all meeting directories under meetings_root."""
    scanned = 0
    renamed = 0
    skipped = 0

    for src_dir in iter_meeting_dirs(meetings_root):
        scanned += 1
        try:
            target_dir = target_for_existing_dir(src_dir, meetings_root)
        except Exception as exc:
            skipped += 1
            logger.warning("Skip %s: failed to read metadata (%s)", src_dir, exc)
            continue

        if src_dir.resolve() == target_dir.resolve():
            skipped += 1
            logger.info("Keep %s (already normalized)", src_dir)
            continue

        if target_dir.exists():
            skipped += 1
            logger.warning("Skip %s: target already exists (%s)", src_dir, target_dir)
            continue

        logger.info("Rename %s -> %s", src_dir, target_dir)
        if dry_run:
            renamed += 1
            continue

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_dir), str(target_dir))
        renamed += 1

    return scanned, renamed, skipped


def main():
    parser = argparse.ArgumentParser(
        description="Rename Telemost meeting dirs to YYYY-MM/date localtime_mailbox_uid layout",
    )
    parser.add_argument(
        "--meetings",
        default=None,
        help="Override meetings root (default: {data_dir}/meetings)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned renames without moving directories",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    runtime = load_runtime_context(__file__)
    data_dir = runtime.data_dir

    meetings_root = (
        Path(args.meetings)
        if args.meetings
        else data_dir / "meetings"
    )

    scanned, renamed, skipped = migrate_meeting_dirs(
        meetings_root=meetings_root,
        dry_run=args.dry_run,
    )

    mode = "DRY-RUN" if args.dry_run else "APPLY"
    print(
        f"[{mode}] scanned={scanned} renamed={renamed} skipped={skipped} root={meetings_root}"
    )


if __name__ == "__main__":
    main()
