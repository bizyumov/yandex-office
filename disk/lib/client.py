#!/usr/bin/env python3
"""Public import facade for Yandex Disk library layers.

Keep this module small: provider calls live in ``disk.lib.api`` and business
workflows live in ``disk.lib.workflows``. Existing callers can continue importing
from ``disk.lib.client`` while architecture and docs point at the split layers.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from disk.lib.api import API_BASE, DiskApi
from disk.lib.workflows import (
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

__all__ = [
    "API_BASE",
    "DiskApi",
    "DiskRead",
    "DiskShare",
    "DiskWrite",
    "YandexDisk",
    "is_private_disk_path",
    "is_public_url",
    "load_manifest_entries",
    "normalize_private_path",
    "normalize_resource",
    "redact_text",
    "safe_local_name",
    "safe_relative_path",
    "surface_for_path",
    "url_host",
    "validate_relative_member",
]
