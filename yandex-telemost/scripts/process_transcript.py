#!/usr/bin/env python3
"""
Telemost transcript transformer.

Takes raw Telemost transcript text and:
1. Parses first-line timestamp into reference UTC datetime
2. Converts diarization time offsets [HH:MM:SS] into absolute UTC timestamps
3. Prepends UTC timestamps to speaker diarization lines
4. Removes inline [HH:MM:SS] markers from body
"""

import re
from datetime import datetime, timedelta, timezone

# MSK is UTC+3
MSK = timezone(timedelta(hours=3))

# Pattern: "Встреча проходила DD.MM.YYYY с HH:MM (MSK)."
HEADER_RE = re.compile(
    r'(\d{2})\.(\d{2})\.(\d{4})\s+\u0441\s+(\d{1,2}):(\d{2})\s+\(MSK\)'
)

# Diarization line: "Speaker Name:" or "Speaker Name (голос 1):"
SPEAKER_RE = re.compile(r'^(.+):\s*$')

# Time marker: "[00:05:36]"
TIME_MARKER_RE = re.compile(r'\[(\d{2}):(\d{2}):(\d{2})\]')


def parse_reference_timestamp(header_line: str) -> datetime | None:
    """Parse first line into a UTC datetime.

    Input: "Встреча проходила DD.MM.YYYY с HH:MM (MSK). ..."
    Returns: corresponding UTC datetime
    """
    m = HEADER_RE.search(header_line)
    if not m:
        return None
    day, month, year, hour, minute = (int(x) for x in m.groups())
    msk_dt = datetime(year, month, day, hour, minute, tzinfo=MSK)
    return msk_dt.astimezone(timezone.utc)


def parse_time_offset(marker_match: re.Match) -> timedelta:
    """Convert [HH:MM:SS] match into a timedelta offset."""
    h, m, s = int(marker_match.group(1)), int(marker_match.group(2)), int(marker_match.group(3))
    return timedelta(hours=h, minutes=m, seconds=s)


def format_utc(dt: datetime) -> str:
    """Format datetime as compact ISO-8601 UTC string."""
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def transform_transcript(raw_text: str) -> tuple[str, datetime | None, list[str]]:
    """Transform raw Telemost transcript.

    Returns (transformed_text, reference_utc, speakers_found).
    """
    lines = raw_text.split('\n')
    if not lines:
        return raw_text, None, []

    ref_utc = parse_reference_timestamp(lines[0])

    output_lines = []
    speakers = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Keep header as-is
        if i == 0:
            output_lines.append(line)
            i += 1
            continue

        # Speaker diarization line
        speaker_match = SPEAKER_RE.match(line)
        if speaker_match and ref_utc is not None:
            speaker_name = speaker_match.group(1)
            if speaker_name not in speakers:
                speakers.append(speaker_name)

            # Look ahead for next time marker
            offset_dt = None
            for j in range(i + 1, len(lines)):
                tm = TIME_MARKER_RE.search(lines[j])
                if tm:
                    offset = parse_time_offset(tm)
                    offset_dt = ref_utc + offset
                    break

            if offset_dt:
                output_lines.append(f'{format_utc(offset_dt)} {speaker_name}:')
            else:
                output_lines.append(line)
            i += 1
            continue

        # Regular lines: strip time markers
        cleaned = TIME_MARKER_RE.sub('', line).lstrip()
        output_lines.append(cleaned)
        i += 1

    return '\n'.join(output_lines), ref_utc, speakers
