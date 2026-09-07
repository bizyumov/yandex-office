"""Optional S3/Object Storage bridge for large Yandex Disk uploads.

The bridge is deliberately outside the core Disk import path: boto3 remains an
opt-in dependency, S3 credentials are resolved by boto3's normal runtime
providers, and the Disk side still uses the managed-auth ``YandexDisk`` client.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.config import load_runtime_context
from disk.lib.workflows import YandexDisk, redact_text, surface_for_path, url_host


logger = logging.getLogger("YandexDiskS3")


@dataclass(frozen=True)
class S3BridgeConfig:
    """Resolved non-secret S3 settings for one bridge invocation."""

    endpoint_url: str
    region: str
    bucket: str
    prefix: str
    presign_ttl_seconds: int
    cleanup_after_disk_import: bool
    multipart_threshold_mib: int
    multipart_chunk_mib: int
    max_concurrency: int | None


def configure_logging(verbose: bool) -> None:
    """Configure bridge logging without changing the global Disk modules."""

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def print_json(payload: object, *, stream=None) -> None:
    """Emit structured bridge output without leaking presigned URLs."""

    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False), file=stream)


def _coalesce(*values: Any) -> Any:
    """Return the first CLI/config value that is intentionally set."""

    for value in values:
        if value is not None and value != "":
            return value
    return None


def load_boto3() -> Any:
    """Import boto3 lazily so normal Disk commands do not require it."""

    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised in environments without boto3
        raise RuntimeError(
            "boto3 is required only for disk.py s3-upload; install it before using the S3 bridge"
        ) from exc
    return boto3


def load_transfer_config() -> Any:
    """Import boto3's transfer config lazily for multipart tuning."""

    try:
        from boto3.s3.transfer import TransferConfig  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - same optional dependency as boto3
        raise RuntimeError("boto3.s3.transfer.TransferConfig is required for S3 multipart uploads") from exc
    return TransferConfig


def sha256_file(path: Path) -> str:
    """Hash a local file when the caller requests sidecar or download proof."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_s3_config(args: argparse.Namespace) -> S3BridgeConfig:
    """Merge ``disk.s3`` config with non-secret CLI overrides."""

    runtime = load_runtime_context(__file__, data_dir_override=args.data_dir)
    config = ((runtime.config.get("disk") or {}).get("s3") or {})
    bucket = _coalesce(args.s3_bucket, config.get("bucket"))
    if not bucket:
        raise RuntimeError("Missing S3 bucket: set disk.s3.bucket or pass --s3-bucket")
    endpoint_url = _coalesce(args.s3_endpoint_url, config.get("endpoint_url"))
    region = _coalesce(args.s3_region, config.get("region"))
    prefix = _coalesce(args.s3_prefix, config.get("prefix"), "")
    ttl = int(_coalesce(args.presign_ttl_seconds, config.get("presign_ttl_seconds"), 7200))
    cleanup = bool(_coalesce(config.get("cleanup_after_disk_import"), True))
    multipart_threshold = int(
        _coalesce(args.multipart_threshold_mib, config.get("multipart_threshold_mib"), 64)
    )
    multipart_chunk = int(_coalesce(args.multipart_chunk_mib, config.get("multipart_chunk_mib"), 64))
    max_concurrency = _coalesce(args.max_concurrency, config.get("max_concurrency"))
    return S3BridgeConfig(
        endpoint_url=str(endpoint_url or "https://storage.yandexcloud.net"),
        region=str(region or "ru-central1"),
        bucket=str(bucket),
        prefix=str(prefix or ""),
        presign_ttl_seconds=ttl,
        cleanup_after_disk_import=cleanup,
        multipart_threshold_mib=multipart_threshold,
        multipart_chunk_mib=multipart_chunk,
        max_concurrency=int(max_concurrency) if max_concurrency is not None else None,
    )


def object_key(prefix: str, key: str | None, local_path: Path) -> str:
    """Choose an S3 object key without deriving local filesystem paths."""

    if key:
        return str(key).lstrip("/")
    clean_prefix = "/".join(part.strip("/") for part in str(prefix or "").split("/") if part.strip("/"))
    return "/".join(part for part in (clean_prefix, local_path.name) if part)


def create_s3_client(config: S3BridgeConfig) -> Any:
    """Create an S3 client while leaving credentials to boto3 providers."""

    boto3 = load_boto3()
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        region_name=config.region,
    )


def upload_to_s3(
    client: Any,
    config: S3BridgeConfig,
    key: str,
    path: Path,
) -> None:
    """Upload and verify object size before any presigned URL is created."""

    TransferConfig = load_transfer_config()
    transfer_kwargs = {
        "multipart_threshold": int(config.multipart_threshold_mib) * 1024 * 1024,
        "multipart_chunksize": int(config.multipart_chunk_mib) * 1024 * 1024,
    }
    if config.max_concurrency is not None:
        transfer_kwargs["max_concurrency"] = config.max_concurrency
    transfer_config = TransferConfig(**transfer_kwargs)
    client.upload_file(str(path), config.bucket, key, Config=transfer_config)
    head = client.head_object(Bucket=config.bucket, Key=key)
    remote_size = int(head.get("ContentLength", -1))
    local_size = path.stat().st_size
    if remote_size != local_size:
        raise RuntimeError(f"S3 size mismatch for {key}: local={local_size} remote={remote_size}")


def put_text_object(client: Any, config: S3BridgeConfig, key: str, text: str) -> None:
    """Upload a small text sidecar only when the caller explicitly requests it."""

    client.put_object(Bucket=config.bucket, Key=key, Body=text.encode("utf-8"), ContentType="text/plain")


def presign_get(client: Any, config: S3BridgeConfig, key: str) -> str:
    """Generate a temporary GET URL that remains in memory only."""

    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": config.bucket, "Key": key},
        ExpiresIn=config.presign_ttl_seconds,
    )


def cleanup_objects(client: Any, config: S3BridgeConfig, keys: list[str]) -> dict[str, Any]:
    """Best-effort cleanup for temporary S3 staging objects."""

    deleted: list[str] = []
    errors: list[dict[str, str]] = []
    for key in keys:
        try:
            client.delete_object(Bucket=config.bucket, Key=key)
            deleted.append(key)
        except Exception as exc:  # noqa: BLE001 - cleanup evidence must preserve failures
            errors.append({"key": key, "error": str(exc)})
    return {"attempted": True, "deleted": deleted, "errors": errors}


def verify_disk_sha256(disk: YandexDisk, remote_path: str, expected: str) -> dict[str, Any]:
    """Download final Disk object and compare SHA-256 only on explicit request."""

    with tempfile.TemporaryDirectory(prefix="yadisk-s3-verify-") as tmp:
        target = Path(tmp) / "download.bin"
        result = disk.download_private_file(
            remote_path,
            output_dir=str(target.parent),
            filename=target.name,
            overwrite=True,
        )
        actual = sha256_file(target)
    if actual != expected:
        raise RuntimeError(f"Disk SHA-256 mismatch: expected={expected} actual={actual}")
    return {
        "verified": True,
        "sha256": actual,
        "bytes": result.get("size"),
        "surface": result.get("surface"),
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the opt-in S3 bridge parser with no secret CLI options."""

    parser = argparse.ArgumentParser(description="Upload to Yandex Disk via temporary S3 presigned URL")
    parser.add_argument("--local", required=True, help="Local file to upload")
    parser.add_argument("--remote", required=True, help="Destination disk:/ or app:/ path")
    parser.add_argument("--account", help="Managed auth account name")
    parser.add_argument("--data-dir", help="Managed auth data directory")
    parser.add_argument("--s3-endpoint-url", help="S3 endpoint override")
    parser.add_argument("--s3-region", help="S3 region override")
    parser.add_argument("--s3-bucket", help="S3 bucket override")
    parser.add_argument("--s3-prefix", help="S3 object prefix override")
    parser.add_argument("--s3-key", help="Exact S3 object key override")
    parser.add_argument("--presign-ttl-seconds", type=int, help="Presigned URL TTL override")
    parser.add_argument("--multipart-threshold-mib", type=int, help="S3 multipart threshold in MiB")
    parser.add_argument("--multipart-chunk-mib", type=int, help="S3 multipart chunk size in MiB")
    parser.add_argument("--max-concurrency", type=int, help="boto3 transfer max_concurrency")
    parser.add_argument("--no-create-parents", action="store_true", help="Do not auto-create Disk parent dirs")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing Yandex Disk destination")
    parser.add_argument("--sha256-sidecar", action="store_true", help="Upload and import <remote>.sha256")
    parser.add_argument("--verify-download-hash", action="store_true", help="Download final Disk object and verify SHA-256")
    parser.add_argument("--keep-s3", action="store_true", help="Do not remove temporary S3 objects")
    parser.add_argument("--poll-timeout", type=float, default=1800.0, help="Yandex Disk operation timeout in seconds")
    parser.add_argument("--poll-interval", type=float, default=3.0, help="Yandex Disk operation poll interval")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser


def s3_upload_main(argv: list[str] | None = None) -> int:
    """Run the S3 bridge and report sanitized timing/cleanup evidence."""

    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    local_path = Path(args.local).expanduser().resolve()
    if not local_path.is_file():
        print_json({"ok": False, "error": f"Not a file: {local_path}"}, stream=sys.stderr)
        return 1

    presigned_urls: list[str] = []
    s3_keys: list[str] = []
    client = None
    config: S3BridgeConfig | None = None
    start = time.monotonic()

    try:
        config = resolve_s3_config(args)
        client = create_s3_client(config)
        key = object_key(config.prefix, args.s3_key, local_path)
        s3_keys.append(key)
        size = local_path.stat().st_size
        digest = sha256_file(local_path) if (args.sha256_sidecar or args.verify_download_hash) else None

        upload_started = time.monotonic()
        upload_to_s3(client, config, key, local_path)
        s3_upload_seconds = time.monotonic() - upload_started

        source_url = presign_get(client, config, key)
        presigned_urls.append(source_url)

        disk = YandexDisk(account=args.account, data_dir=args.data_dir)
        created_dirs = [] if args.no_create_parents else disk.ensure_parent_dirs(args.remote)
        import_started = time.monotonic()
        disk_result = disk.upload_from_url(
            source_url=source_url,
            remote_path=args.remote,
            overwrite=args.overwrite,
            wait=True,
            timeout_seconds=int(args.poll_timeout),
            poll_seconds=int(args.poll_interval),
            verify_size=size,
        )
        disk_import_seconds = time.monotonic() - import_started

        sidecar_result = None
        if args.sha256_sidecar:
            assert digest is not None
            sidecar_text = f"{digest}  {local_path.name}\n"
            sidecar_key = f"{key}.sha256"
            sidecar_remote = f"{args.remote}.sha256"
            s3_keys.append(sidecar_key)
            put_text_object(client, config, sidecar_key, sidecar_text)
            sidecar_url = presign_get(client, config, sidecar_key)
            presigned_urls.append(sidecar_url)
            sidecar_result = disk.upload_from_url(
                source_url=sidecar_url,
                remote_path=sidecar_remote,
                overwrite=args.overwrite,
                wait=True,
                timeout_seconds=int(args.poll_timeout),
                poll_seconds=int(args.poll_interval),
                verify_size=len(sidecar_text.encode("utf-8")),
            )

        verify_result = None
        if args.verify_download_hash:
            assert digest is not None
            verify_result = verify_disk_sha256(disk, args.remote, digest)

        if args.keep_s3 or not config.cleanup_after_disk_import:
            cleanup_result = {"attempted": False, "preserved": s3_keys}
        else:
            cleanup_result = cleanup_objects(client, config, s3_keys)

        print_json(
            {
                "ok": True,
                "surface": surface_for_path(args.remote),
                "remote_path": args.remote,
                "local_path": str(local_path),
                "bytes": size,
                "created_dirs": created_dirs,
                "sha256": digest,
                "hash": None,
                "hash_status": "not_provided",
                "s3": {
                    "endpoint_host": url_host(config.endpoint_url),
                    "region": config.region,
                    "bucket_configured": True,
                    "object_keys": s3_keys,
                    "presigned_urls": "redacted",
                    "cleanup": cleanup_result,
                },
                "disk": disk_result,
                "sidecar": sidecar_result,
                "verify_download_hash": verify_result,
                "timing_seconds": {
                    "s3_upload": round(s3_upload_seconds, 3),
                    "disk_import": round(disk_import_seconds, 3),
                    "total": round(time.monotonic() - start, 3),
                },
            }
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - command-line tool reports JSON
        if (
            client is not None
            and config is not None
            and s3_keys
            and not args.keep_s3
            and config.cleanup_after_disk_import
        ):
            try:
                cleanup_objects(client, config, s3_keys)
            except Exception:  # noqa: BLE001 - original error is the useful one
                logger.debug("S3 cleanup after failure also failed", exc_info=True)
        message = str(exc)
        for url in presigned_urls:
            message = redact_text(message, [url])
        print_json({"ok": False, "error": message, "presigned_urls": "redacted"}, stream=sys.stderr)
        return 1
