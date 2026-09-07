#!/usr/bin/env python3
"""Canonical command adapter for all Disk scenario subcommands."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from disk.lib.cli import build_disk_parser as build_parser, disk_main as main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
