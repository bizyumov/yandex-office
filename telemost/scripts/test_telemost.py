#!/usr/bin/env python3
"""Tests for telemost processor.

T13: Unit test — sample transcript → expected UTC output
T14: Integration test — 'summary' + 'recording' → merged meeting output
T15: Integration test — 'summary' only → partial meeting output
T16: Unit test — enrich_incoming() classifies and extracts metadata
"""

import json
import shutil
import tempfile
from pathlib import Path

from process_transcript import (
    format_utc,
    parse_reference_timestamp,
    transform_transcript,
)
from process_meeting import (
    archive_dirs,
    build_meeting_output_path,
    classify_email,
    enrich_incoming,
    extract_media_links,
    extract_meeting_title,
    extract_meeting_uid,
    group_by_meeting_uid,
    merge_meeting_data,
    process_meeting,
    scan_incoming,
)


# ── Sample data ──────────────────────────────────────────────────────

SAMPLE_TRANSCRIPT = """\
Встреча проходила 08.02.2026 с 19:07 (MSK). В расшифровке могут быть неточности — проверяйте важное.


Алиса Иванова (голос 1):
[00:00:07] Так, ну давай.

Борис Петров (голос 2):
[00:00:10] Наша история начинается в деревне.
[00:00:20] Там есть своя правительница.

Алиса Иванова (голос 1):
[00:00:32] Так, ты рассказывай.
"""

MEETING_UID = "5981404294"
MEETING_DIR = Path("2026-02") / "2026-02-08_19-07_test_5981404294"

YANDEX_GPT_SUMMARY = """\
Участники обсуждали историю деревни и роль правительницы.
Алиса предложила Борису продолжить рассказ.
"""

# Post-enrichment meta (as produced by enrich_incoming + mail)
SUMMARY_META = {
    "imap_uid": 2550,
    "mailbox": "test",
    "subject": "Конспект встречи 8 февр. 2026 г.",
    "sender": "Хранитель встреч Телемоста <keeper@telemost.yandex.ru>",
    "timestamp": "2026-02-08T16:27:00Z",
    "attachments": ["2026-02-08 19:07 (MSK) 5981404294.txt"],
    "dir_name": "2026-02-08_test_uid2550",
    "email_type": "summary",
    "meeting_uid": MEETING_UID,
    "meeting_title": None,
    "media_links": [],
    "telemost_summary": YANDEX_GPT_SUMMARY,
}

RECORDING_META = {
    "imap_uid": 2551,
    "mailbox": "test",
    "subject": "Запись встречи «Стендап» готова",
    "sender": "Хранитель встреч Телемоста <keeper@telemost.yandex.ru>",
    "timestamp": "2026-02-08T17:00:00Z",
    "attachments": [],
    "dir_name": "2026-02-08_test_uid2551",
    "email_type": "recording",
    "meeting_uid": MEETING_UID,
    "meeting_title": "Стендап",
    "media_links": [
        "https://yadi.sk/d/abc123_video",
        "https://yadi.sk/d/def456_audio",
    ],
    "telemost_summary": None,
}


# ── T13: Unit test — transcript transformation ───────────────────────

def test_parse_reference_timestamp():
    """Parse MSK header → UTC datetime."""
    header = "Встреча проходила 08.02.2026 с 19:07 (MSK). Проверяйте."
    ref_utc = parse_reference_timestamp(header)
    assert ref_utc is not None
    # 19:07 MSK = 16:07 UTC
    assert format_utc(ref_utc) == "2026-02-08T16:07:00Z"
    print("  PASS: parse_reference_timestamp → 2026-02-08T16:07:00Z")


def test_transform_transcript():
    """Full transcript transformation with UTC timestamps."""
    transformed, ref_utc, speakers = transform_transcript(SAMPLE_TRANSCRIPT)

    # Check reference
    assert ref_utc is not None
    assert format_utc(ref_utc) == "2026-02-08T16:07:00Z"

    # Check speakers detected
    assert "Алиса Иванова (голос 1)" in speakers
    assert "Борис Петров (голос 2)" in speakers

    lines = transformed.split("\n")

    # Header preserved
    assert lines[0].startswith("Встреча проходила")

    # Speaker lines have UTC timestamps
    utc_speaker_lines = [l for l in lines if l.startswith("2026-")]
    assert len(utc_speaker_lines) == 3  # 3 speaker turns

    # First speaker at 00:00:07 → 16:07:07 UTC
    assert "2026-02-08T16:07:07Z Алиса Иванова (голос 1):" in utc_speaker_lines[0]

    # Second speaker at 00:00:10 → 16:07:10 UTC
    assert "2026-02-08T16:07:10Z Борис Петров (голос 2):" in utc_speaker_lines[1]

    # Third speaker at 00:00:32 → 16:07:32 UTC
    assert "2026-02-08T16:07:32Z Алиса Иванова (голос 1):" in utc_speaker_lines[2]

    # Time markers removed from body
    assert "[00:00:07]" not in transformed
    assert "[00:00:10]" not in transformed

    print(f"  PASS: transform_transcript → {len(utc_speaker_lines)} speaker turns, {len(speakers)} speakers")


def test_transform_no_header():
    """Transcript without recognizable header — graceful degradation."""
    raw = "Some random text\nwith no header\n"
    transformed, ref_utc, speakers = transform_transcript(raw)
    assert ref_utc is None
    assert speakers == []
    print("  PASS: transform_transcript (no header) → graceful None")


# ── T14: Integration test — full merge (summary + recording) ────────

def test_full_merge():
    """Drop both email types → verify merged meeting output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        incoming = tmp / "incoming"
        output = tmp / "output"
        archive = tmp / "archive"

        # Create summary email dir
        summary_dir = incoming / SUMMARY_META["dir_name"]
        summary_dir.mkdir(parents=True)
        (summary_dir / "meta.json").write_text(
            json.dumps({**SUMMARY_META, "dir_path": str(summary_dir)},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        (summary_dir / "2026-02-08 19:07 (MSK) 5981404294.txt").write_text(
            SAMPLE_TRANSCRIPT, encoding="utf-8"
        )
        (summary_dir / "email_body.txt").write_text(
            YANDEX_GPT_SUMMARY, encoding="utf-8"
        )

        # Create recording email dir
        recording_dir = incoming / RECORDING_META["dir_name"]
        recording_dir.mkdir(parents=True)
        (recording_dir / "meta.json").write_text(
            json.dumps({**RECORDING_META, "dir_path": str(recording_dir)},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        (recording_dir / "email_body.txt").write_text(
            "Ссылки на запись: https://yadi.sk/d/abc123_video",
            encoding="utf-8",
        )

        # Run pipeline
        emails = scan_incoming(incoming)
        assert len(emails) == 2, f"Expected 2 emails, got {len(emails)}"

        groups = group_by_meeting_uid(emails)
        assert MEETING_UID in groups, f"Meeting UID {MEETING_UID} not found in groups"
        assert len(groups[MEETING_UID]) == 2

        meeting_data = merge_meeting_data(groups[MEETING_UID])
        assert meeting_data["meeting_uid"] == MEETING_UID
        assert meeting_data["meeting_title"] == "Стендап"
        assert meeting_data["transcript_file"] is not None
        assert meeting_data["summary"] is not None
        assert len(meeting_data["media_links"]) == 2

        result = process_meeting(meeting_data, output)
        assert result is not None
        assert result["has_transcript"]
        assert result["has_summary"]
        assert result["has_recording_links"]
        assert len(result["speakers"]) == 2

        # Check output files
        meeting_dir = build_meeting_output_path(meeting_data, output)
        assert Path(result["meeting_dir"]) == meeting_dir
        assert (meeting_dir / "transcript.txt").exists()
        assert (meeting_dir / "summary.txt").exists()
        assert (meeting_dir / "meeting.meta.json").exists()

        # Check meeting metadata
        meta = json.loads((meeting_dir / "meeting.meta.json").read_text())
        assert meta["title"] == "Стендап"
        assert len(meta["media_links"]) == 2
        assert meta["partial"] is False
        assert len(meta["source_emails"]) == 2

        # Check transcript has UTC timestamps
        transcript = (meeting_dir / "transcript.txt").read_text()
        assert "2026-02-08T16:07:" in transcript

        # Test archiving
        archive_dirs([str(summary_dir), str(recording_dir)], archive)
        assert not summary_dir.exists()
        assert not recording_dir.exists()
        assert (archive / SUMMARY_META["dir_name"]).exists()
        assert (archive / RECORDING_META["dir_name"]).exists()

        print(f"  PASS: full merge → {meeting_dir.name}/ with transcript, summary, recording links")


# ── T15: Integration test — partial meeting (summary only) ───────────

def test_partial_meeting():
    """Only summary arrived → partial meeting, no recording links."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        incoming = tmp / "incoming"
        output = tmp / "output"

        # Create only summary dir
        summary_dir = incoming / SUMMARY_META["dir_name"]
        summary_dir.mkdir(parents=True)
        (summary_dir / "meta.json").write_text(
            json.dumps({**SUMMARY_META, "dir_path": str(summary_dir)},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        (summary_dir / "2026-02-08 19:07 (MSK) 5981404294.txt").write_text(
            SAMPLE_TRANSCRIPT, encoding="utf-8"
        )
        (summary_dir / "email_body.txt").write_text(
            YANDEX_GPT_SUMMARY, encoding="utf-8"
        )

        # Run pipeline
        emails = scan_incoming(incoming)
        assert len(emails) == 1

        groups = group_by_meeting_uid(emails)
        meeting_data = merge_meeting_data(groups[MEETING_UID])

        assert meeting_data["meeting_uid"] == MEETING_UID
        assert meeting_data["meeting_title"] is None  # Only in recording emails
        assert meeting_data["transcript_file"] is not None
        assert len(meeting_data["media_links"]) == 0

        result = process_meeting(meeting_data, output)
        assert result is not None
        assert result["has_transcript"]
        assert result["has_summary"]
        assert not result["has_recording_links"]

        # Check partial flag
        meeting_dir = build_meeting_output_path(meeting_data, output)
        assert Path(result["meeting_dir"]) == meeting_dir
        meta = json.loads((meeting_dir / "meeting.meta.json").read_text())
        assert meta["partial"] is True
        assert len(meta["media_links"]) == 0

        print(f"  PASS: partial meeting → {meeting_dir.name}/ transcript only, partial=true")


# ── T15c: Integration test — existing meta is merged, not overwritten ──

def test_existing_meta_non_destructive_merge():
    """Recording-only reprocess must keep previously saved summary fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        output = tmp / "output"

        meeting_data_summary = {
            "meeting_uid": MEETING_UID,
            "meeting_title": None,
            "meeting_start_local": "2026-02-08T19:07",
            "transcript_file": None,
            "summary_file": None,
            "summary": YANDEX_GPT_SUMMARY,
            "telemost_summary": YANDEX_GPT_SUMMARY,
            "media_links": [],
            "source_emails": [
                {
                    "imap_uid": 2550,
                    "email_type": "summary",
                    "subject": "Конспект встречи",
                    "mailbox": "test",
                    "timestamp": "2026-02-08T16:27:00Z",
                    "meeting_start_local": "2026-02-08T19:07",
                    "dir_name": "2026-02-08_test_uid2550",
                }
            ],
        }

        summary_result = process_meeting(meeting_data_summary, output)
        assert summary_result is not None
        meeting_dir = Path(summary_result["meeting_dir"])

        # Simulate recording-only pass for the same meeting directory.
        meeting_data_recording = {
            "meeting_uid": MEETING_UID,
            "meeting_title": "Стендап",
            "meeting_start_local": "2026-02-08T19:07",
            "transcript_file": None,
            "summary_file": None,
            "summary": None,
            "telemost_summary": None,
            "media_links": [
                "https://yadi.sk/d/abc123_video",
                "https://yadi.sk/d/def456_audio",
            ],
            "source_emails": [
                {
                    "imap_uid": 2551,
                    "email_type": "recording",
                    "subject": "Запись встречи «Стендап» готова",
                    "mailbox": "test",
                    "timestamp": "2026-02-08T17:00:00Z",
                    "meeting_start_local": "2026-02-08T19:07",
                    "dir_name": "2026-02-08_test_uid2551",
                }
            ],
        }
        recording_result = process_meeting(meeting_data_recording, output)
        assert recording_result is not None
        assert Path(recording_result["meeting_dir"]) == meeting_dir

        meta = json.loads((meeting_dir / "meeting.meta.json").read_text(encoding="utf-8"))
        assert meta["telemost_summary"] == YANDEX_GPT_SUMMARY
        assert len(meta["media_links"]) == 2
        assert len(meta["source_emails"]) == 2

        print("  PASS: existing meeting.meta.json is merged non-destructively")


# ── T15b: Standalone dir (no meeting UID) ────────────────────────────

def test_standalone_no_uid():
    """Dir without meeting_uid → grouped by dir_name, still processed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        incoming = tmp / "incoming"
        output = tmp / "output"

        # Manual drop with no meeting_uid
        manual_meta = {
            "imap_uid": 0,
            "mailbox": "manual",
            "subject": "Manual upload",
            "sender": "user",
            "timestamp": "2026-02-12T10:00:00Z",
            "attachments": ["transcript.txt"],
            "dir_name": "2026-02-12_manual_standup-notes",
            "email_type": "summary",
            "meeting_uid": None,
            "meeting_title": None,
            "media_links": [],
            "telemost_summary": None,
        }

        manual_dir = incoming / manual_meta["dir_name"]
        manual_dir.mkdir(parents=True)
        (manual_dir / "meta.json").write_text(
            json.dumps({**manual_meta, "dir_path": str(manual_dir)},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        (manual_dir / "transcript.txt").write_text(
            SAMPLE_TRANSCRIPT, encoding="utf-8"
        )

        emails = scan_incoming(incoming)
        groups = group_by_meeting_uid(emails)

        # Grouped by dir_name since meeting_uid is None
        assert manual_meta["dir_name"] in groups

        meeting_data = merge_meeting_data(groups[manual_meta["dir_name"]])
        result = process_meeting(meeting_data, output)

        assert result is not None
        assert result["has_transcript"]
        meeting_dir = build_meeting_output_path(meeting_data, output)
        assert Path(result["meeting_dir"]) == meeting_dir
        assert (meeting_dir / "meeting.meta.json").exists()

        print("  PASS: standalone (no UID) → processed by dir_name")


# ── T16: Unit test — enrich_incoming() ───────────────────────────────

def test_enrich_incoming():
    """enrich_incoming() classifies emails and extracts meeting metadata from plain text."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        incoming = tmp / "incoming"

        # Create a raw (un-enriched) summary email dir
        raw_dir = incoming / "2026-02-08_test_uid2550"
        raw_dir.mkdir(parents=True)

        raw_meta = {
            "imap_uid": 2550,
            "mailbox": "test",
            "subject": "Конспект встречи от 08.02.2026",
            "sender": "Хранитель встреч Телемоста <keeper@telemost.yandex.ru>",
            "timestamp": "2026-02-08T16:27:00Z",
            "attachments": ["2026-02-08 19:07 (MSK) 5981404294.txt"],
            "dir_name": "2026-02-08_test_uid2550",
        }
        (raw_dir / "meta.json").write_text(
            json.dumps(raw_meta, ensure_ascii=False), encoding="utf-8"
        )
        body_text = (
            "Конспектирование началось 08.02.2026 в 19:07 (MSK)\n"
            "Ссылка на встречу: https://telemost.yandex.ru/j/5981404294\n"
            f"{YANDEX_GPT_SUMMARY}"
        )
        (raw_dir / "email_body.txt").write_text(body_text, encoding="utf-8")

        # Create a non-telemost email (should be skipped)
        other_dir = incoming / "2026-02-08_test_uid9999"
        other_dir.mkdir(parents=True)
        other_meta = {
            "imap_uid": 9999,
            "mailbox": "test",
            "subject": "Newsletter",
            "sender": "news@example.com",
            "timestamp": "2026-02-08T10:00:00Z",
            "attachments": [],
            "dir_name": "2026-02-08_test_uid9999",
        }
        (other_dir / "meta.json").write_text(
            json.dumps(other_meta, ensure_ascii=False), encoding="utf-8"
        )

        # Run enrichment
        count = enrich_incoming(incoming)
        assert count == 1, f"Expected 1 enriched, got {count}"

        # Check enriched meta
        enriched = json.loads((raw_dir / "meta.json").read_text(encoding="utf-8"))
        assert enriched["email_type"] == "summary"
        assert enriched["meeting_uid"] == "5981404294"
        assert enriched["meeting_title"] is None
        assert enriched["media_links"] == []
        assert enriched["meeting_start_local"] == "2026-02-08T19:07"
        assert enriched["telemost_summary"] == body_text

        # Check non-telemost email was NOT enriched
        other = json.loads((other_dir / "meta.json").read_text(encoding="utf-8"))
        assert "email_type" not in other

        # Run again - already-enriched should be skipped
        count2 = enrich_incoming(incoming)
        assert count2 == 0, f"Expected 0 on re-run, got {count2}"

        print("  PASS: enrich_incoming -> classified, extracted, idempotent")


def test_classify_email():
    """classify_email returns English names, not transliterations."""
    assert classify_email("Конспект встречи от 08.02.2026") == "summary"
    assert classify_email("Запись встречи «Стендап» готова") == "recording"
    assert classify_email("Random subject") == "unknown"
    print("  PASS: classify_email → summary/recording/unknown")


def test_build_meeting_output_path():
    """Output path includes YYYY-MM bucket and date+HH-MM mailbox prefix."""
    meeting_data = {
        "meeting_uid": MEETING_UID,
        "date": "2026-02-08T16:27:00Z",
        "source_emails": [
            {"mailbox": "test", "timestamp": "2026-02-08T16:27:00Z", "dir_name": "2026-02-08_test_uid2550"}
        ],
    }
    path = build_meeting_output_path(meeting_data, Path("/tmp/out"))
    assert path == Path("/tmp/out/2026-02/2026-02-08_19-27_test_5981404294")
    print("  PASS: build_meeting_output_path → YYYY-MM/date_HH-MM_tag_uid")


# ── Runner ───────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("T13a", test_parse_reference_timestamp),
        ("T13b", test_transform_transcript),
        ("T13c", test_transform_no_header),
        ("T14",  test_full_merge),
        ("T15a", test_partial_meeting),
        ("T15c", test_existing_meta_non_destructive_merge),
        ("T15b", test_standalone_no_uid),
        ("T16a", test_enrich_incoming),
        ("T16b", test_classify_email),
        ("T16c", test_build_meeting_output_path),
    ]

    passed = 0
    failed = 0
    for label, fn in tests:
        print(f"\n[{label}] {fn.__doc__}")
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    return failed == 0


if __name__ == "__main__":
    import sys
    ok = run_all()
    sys.exit(0 if ok else 1)
