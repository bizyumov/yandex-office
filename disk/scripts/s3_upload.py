#!/usr/bin/env python3
"""Command adapter for the optional Disk S3/Object Storage bridge."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from disk.lib.s3 import (  # noqa: E402,F401
    S3BridgeConfig,
    build_parser,
    cleanup_objects,
    configure_logging,
    create_s3_client,
    load_boto3,
    load_transfer_config,
    object_key,
    presign_get,
    print_json,
    resolve_s3_config,
    s3_upload_main as main,
    sha256_file,
    upload_to_s3,
    verify_disk_sha256,
)


if __name__ == "__main__":
    raise SystemExit(main())
