#!/usr/bin/env python3
"""Command adapter for Disk file-management workflows."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from disk.lib.cli import build_manage_parser as build_parser, manage_main as main  # noqa: E402
from disk.lib.workflows import YandexDisk  # noqa: E402,F401


if __name__ == "__main__":
    raise SystemExit(main())
