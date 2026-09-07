#!/usr/bin/env python3
"""Command adapter for Disk share-only workflows."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from disk.lib.cli import (  # noqa: E402,F401
    add_common_auth,
    add_path_arg,
    add_share_options,
    build_share_kwargs,
    build_share_parser as build_parser,
    share_main as main,
)
from disk.lib.workflows import YandexDisk  # noqa: E402,F401

_build_share_kwargs = build_share_kwargs


if __name__ == "__main__":
    raise SystemExit(main())
