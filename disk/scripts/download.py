#!/usr/bin/env python3
"""Command adapter for Disk read and materialization workflows."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from disk.lib.api import API_BASE, DiskApi  # noqa: E402,F401
from disk.lib.workflows import (  # noqa: E402,F401
    DiskRead,
    DiskShare,
    DiskWrite,
    YandexDisk,
    is_private_disk_path,
    is_public_url,
    load_manifest_entries,
    normalize_private_path,
    normalize_resource,
    redact_text,
    safe_local_name,
    safe_relative_path,
    surface_for_path,
    url_host,
    validate_relative_member,
)
from disk.lib.cli import build_download_parser as build_parser, download_main as main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
