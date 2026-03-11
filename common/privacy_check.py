#!/usr/bin/env python3
"""Pre-publish privacy scan for the tracked Yandex skill tree."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
ORG_ID_RE = re.compile(r"\b\d{7,}\b")
TOKEN_RE = re.compile(r"\by0_[A-Za-z0-9_-]{8,}\b")

ALLOWED_EMAILS = {
    "news@example.com",
    "user@example.com",
    "user@yandex.ru",
    "contact@example.com",
    "colleague@yandex.ru",
    "keeper@telemost.yandex.ru",
    "xml@yandex-team.ru",
}

ALLOWED_ORG_IDS = {
    "123456",
}

SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".xlsx",
    ".eml",
}


def tracked_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [repo_root / line for line in result.stdout.splitlines() if line]


def scan_file(path: Path) -> list[str]:
    if path.suffix in SKIP_SUFFIXES:
        return []

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    findings: list[str] = []

    for email in sorted(set(EMAIL_RE.findall(text))):
        if email not in ALLOWED_EMAILS:
            findings.append(f"unexpected email: {email}")

    for org_id in sorted(set(ORG_ID_RE.findall(text))):
        if org_id not in ALLOWED_ORG_IDS and "orgId" in text:
            findings.append(f"unexpected org id: {org_id}")

    for token in sorted(set(TOKEN_RE.findall(text))):
        findings.append(f"token-looking string: {token[:12]}...")

    return findings


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    files = tracked_files(repo_root)
    failures: list[tuple[Path, str]] = []

    for path in files:
        if path.suffix == ".token":
            failures.append((path, "tracked token file"))
            continue
        for finding in scan_file(path):
            failures.append((path, finding))

    if failures:
        for path, finding in failures:
            rel = path.relative_to(repo_root)
            print(f"{rel}: {finding}", file=sys.stderr)
        return 1

    print("privacy check: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
