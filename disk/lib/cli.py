"""Command facade for Yandex Disk workflows.

The Disk skill exposes commands for agents, but command files should not own
provider calls or business policy.  This module translates CLI arguments into
the shared read, write, and share workflow layers.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from disk.lib.workflows import (
    YandexDisk,
    is_private_disk_path,
    is_public_url,
    normalize_resource,
    redact_text,
    surface_for_path,
)
from disk.lib.s3 import build_parser as build_s3_parser
from disk.lib.s3 import s3_upload_main


def configure_logging(verbose: bool) -> None:
    """Configure CLI logging consistently for Disk command adapters."""

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def print_json(payload: object, *, stream=None) -> None:
    """Print structured CLI output without leaking implementation objects."""

    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False), file=stream)


def _csv_list(value: str | None) -> list[str] | None:
    """Parse comma-separated share identifiers from CLI options."""

    if value is None:
        return None
    items = [item.strip() for item in value.split(",")]
    items = [item for item in items if item]
    return items or None


def build_share_kwargs(args: argparse.Namespace) -> dict:
    """Translate share CLI options into DiskShare keyword arguments."""

    return {
        "path": args.path,
        "access": args.access,
        "org_id": args.org_id,
        "rights": args.rights,
        "password": args.password,
        "available_until": args.available_until,
        "user_ids": _csv_list(args.user_ids),
        "group_ids": _csv_list(args.group_ids),
        "department_ids": _csv_list(args.department_ids),
    }


def add_common_auth(parser: argparse.ArgumentParser) -> None:
    """Add managed-auth selectors shared by private Disk commands."""

    parser.add_argument("--account", help="Account name for managed token resolution")
    parser.add_argument("--data-dir", help="Explicit Yandex data directory override")


def add_path_arg(
    parser: argparse.ArgumentParser,
    *,
    option: str = "--path",
    help_text: str = "Disk resource path (e.g. disk:/foo/bar.txt)",
) -> None:
    """Add a required Disk path argument with one consistent help string."""

    parser.add_argument(option, required=True, help=help_text)


def add_share_options(parser: argparse.ArgumentParser) -> None:
    """Add share-policy options without implementing the policy in the CLI."""

    parser.add_argument("--access", choices=["employees", "all"], help="Access macro")
    parser.add_argument(
        "--org-id",
        help="Organization ID for employees access; optional if stored as org_id in the token file",
    )
    parser.add_argument(
        "--rights",
        choices=[
            "read",
            "write",
            "read_without_download",
            "read_with_password",
            "read_with_password_without_download",
        ],
        help="Share rights mode",
    )
    parser.add_argument("--password", help="Password for protected share modes")
    parser.add_argument(
        "--available-until",
        type=int,
        help="TTL in seconds; future Unix timestamps are also accepted for compatibility",
    )
    parser.add_argument("--user-ids", help="Comma-separated user IDs")
    parser.add_argument("--group-ids", help="Comma-separated group IDs")
    parser.add_argument("--department-ids", help="Comma-separated department IDs")


def build_download_parser() -> argparse.ArgumentParser:
    """Build the read/materialization command parser."""

    parser = argparse.ArgumentParser(
        description="Download Yandex Disk public links or authenticated disk:/ and app:/ paths",
    )
    parser.add_argument("url", nargs="?", help="Public link or authenticated disk:/ / app:/ path")
    parser.add_argument("--output", "-o", default=".", help="Output directory")
    parser.add_argument("--filename", "-f", help="Override output filename")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing local output")
    add_common_auth(parser)
    parser.add_argument("--meta", action="store_true", help="Print file metadata as JSON")
    parser.add_argument(
        "--materialize-dir",
        action="store_true",
        help="For public folders, download members as files instead of the generated archive",
    )
    parser.add_argument(
        "--flatten-single-root",
        action="store_true",
        help="For public folders, imply --materialize-dir and omit the public folder wrapper",
    )
    parser.add_argument("--manifest", help="JSON array or JSONL manifest of private disk:/ or app:/ files")
    parser.add_argument("--source-root", help="Private disk:/ or app:/ source root")
    parser.add_argument("--dry-run", action="store_true", help="Plan selected materialization only")
    parser.add_argument("--anonymous", action="store_true", help="Deprecated public-link compatibility flag")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    return parser


def download_main(argv: list[str] | None = None) -> int:
    """Run the read/materialization CLI against shared DiskRead workflows."""

    parser = build_download_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    disk = YandexDisk(account=args.account, data_dir=args.data_dir)
    try:
        if args.manifest:
            if not args.source_root:
                raise ValueError("--source-root is required with --manifest")
            result = disk.materialize_selected_private(
                manifest_path=args.manifest,
                source_root=args.source_root,
                output_dir=args.output,
                overwrite=args.overwrite,
                dry_run=args.dry_run,
            )
        elif is_private_disk_path(args.url):
            if args.meta:
                meta = disk.get_resource_meta(args.url)
                result = normalize_resource(meta, surface=surface_for_path(args.url))
            else:
                result = disk.download_private_file(
                    args.url,
                    output_dir=args.output,
                    filename=args.filename,
                    overwrite=args.overwrite,
                )
        else:
            if not args.url:
                raise ValueError("url is required unless --manifest is used")
            if not is_public_url(args.url):
                raise ValueError(f"Unsupported download source: {args.url!r}")
            if args.meta:
                result = disk.get_public_meta(args.url, anonymous=args.anonymous)
                result["surface"] = "public-link"
            else:
                result = disk.download_with_meta(
                    args.url,
                    output_dir=args.output,
                    filename=args.filename,
                    anonymous=args.anonymous,
                    materialize_dir=args.materialize_dir,
                    flatten_single_root=args.flatten_single_root,
                    overwrite=args.overwrite,
                )
        print_json(result)
        return 0
    except (RuntimeError, ValueError, FileNotFoundError, TimeoutError) as exc:
        print_json({"error": str(exc)}, stream=sys.stderr)
        return 1


def build_list_parser() -> argparse.ArgumentParser:
    """Build the authenticated folder browsing command parser."""

    parser = argparse.ArgumentParser(description="List authenticated Yandex Disk folders")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    add_common_auth(parser)
    parser.add_argument("--path", required=True, help="Folder path, e.g. disk:/Docs or app:/")
    parser.add_argument("--limit", type=int, default=100, help="Page size for provider listing")
    parser.add_argument("--offset", type=int, default=0, help="Offset for non-recursive listing")
    parser.add_argument("--recursive", action="store_true", help="Recursively list child folders")
    parser.add_argument("--jsonl", action="store_true", help="Print one JSON object per resource")
    return parser


def list_main(argv: list[str] | None = None) -> int:
    """Run the authenticated folder browsing CLI."""

    parser = build_list_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    disk = YandexDisk(account=args.account, data_dir=args.data_dir)
    try:
        if args.recursive:
            items = disk.list_tree(args.path, limit=args.limit, recursive=True)
        else:
            meta = disk.list_resource(args.path, limit=args.limit, offset=args.offset)
            embedded = meta.get("_embedded") or {}
            items = [
                normalize_resource(item, surface=surface_for_path(args.path))
                for item in embedded.get("items") or []
            ]
        if args.jsonl:
            for item in items:
                print(json.dumps(item, ensure_ascii=False, sort_keys=True))
        else:
            print_json(
                {
                    "surface": surface_for_path(args.path),
                    "path": args.path,
                    "recursive": bool(args.recursive),
                    "items": items,
                }
            )
        return 0
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print_json({"error": str(exc)}, stream=sys.stderr)
        return 1


def build_share_parser() -> argparse.ArgumentParser:
    """Build the share-management command parser."""

    parser = argparse.ArgumentParser(description="Manage Yandex Disk share links")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("publish", "Publish a resource and create share link"),
        ("update", "Update existing share settings"),
        ("info", "Get current share info"),
        ("unpublish", "Unpublish a resource"),
    ):
        subparser = subparsers.add_parser(command, help=help_text)
        add_common_auth(subparser)
        add_path_arg(subparser)
        if command in {"publish", "update"}:
            add_share_options(subparser)
    return parser


def share_main(argv: list[str] | None = None) -> int:
    """Run share-management commands against DiskShare workflows."""

    parser = build_share_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    disk = YandexDisk(account=args.account, data_dir=args.data_dir)
    try:
        if args.command == "publish":
            result = disk.publish_file(**build_share_kwargs(args))
        elif args.command == "update":
            result = disk.update_share_settings(**build_share_kwargs(args))
        elif args.command == "info":
            result = disk.get_share_info(args.path)
        elif args.command == "unpublish":
            result = disk.unpublish_file(args.path)
        else:
            parser.error(f"Unsupported command: {args.command}")
        print_json(result)
        return 0
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print_json({"error": str(exc)}, stream=sys.stderr)
        return 1


def build_upload_parser() -> argparse.ArgumentParser:
    """Build the direct upload command parser."""

    parser = argparse.ArgumentParser(description="Upload files to Yandex Disk")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    add_common_auth(parser)
    parser.add_argument("--local", required=True, help="Local file path to upload")
    parser.add_argument("--remote", required=True, help="Destination disk:/ or app:/ path")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing remote file")
    parser.add_argument("--no-create-parents", action="store_true", help="Do not auto-create parent dirs")
    parser.add_argument("--publish", action="store_true", help="Publish the uploaded file after upload")
    add_share_options(parser)
    return parser


def upload_main(argv: list[str] | None = None) -> int:
    """Run direct upload and optional publish composition."""

    parser = build_upload_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    disk = YandexDisk(account=args.account, data_dir=args.data_dir)
    try:
        if args.publish:
            share_kwargs = build_share_kwargs(argparse.Namespace(**{**vars(args), "path": args.remote}))
            share_kwargs.pop("path", None)
            result = disk.upload_and_publish(
                args.local,
                args.remote,
                overwrite=args.overwrite,
                create_parents=not args.no_create_parents,
                **share_kwargs,
            )
        else:
            result = disk.upload_file(
                args.local,
                args.remote,
                overwrite=args.overwrite,
                create_parents=not args.no_create_parents,
            )
        print_json(result)
        return 0
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print_json({"error": str(exc)}, stream=sys.stderr)
        return 1


def build_import_url_parser() -> argparse.ArgumentParser:
    """Build the URL-import command parser."""

    parser = argparse.ArgumentParser(description="Import a URL into disk:/ or app:/")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    add_common_auth(parser)
    parser.add_argument("--source-url", required=True, help="Source URL to import; never printed")
    parser.add_argument("--remote", required=True, help="Destination path, e.g. disk:/Docs/file.bin")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing destination")
    parser.add_argument("--disable-redirects", action="store_true", help="Ask Disk not to follow redirects")
    parser.add_argument("--wait", action="store_true", help="Wait for Disk async operation")
    parser.add_argument("--timeout-seconds", type=int, default=7200, help="Operation wait timeout")
    parser.add_argument("--poll-seconds", type=int, default=10, help="Operation poll interval")
    parser.add_argument("--verify-size", type=int, help="Expected final Disk metadata size")
    return parser


def import_url_main(argv: list[str] | None = None) -> int:
    """Run URL import through DiskWrite upload-from-URL workflow."""

    parser = build_import_url_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    disk = YandexDisk(account=args.account, data_dir=args.data_dir)
    try:
        result = disk.upload_from_url(
            source_url=args.source_url,
            remote_path=args.remote,
            overwrite=args.overwrite,
            disable_redirects=args.disable_redirects,
            wait=args.wait,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
            verify_size=args.verify_size,
        )
        print_json(result)
        return 0
    except (RuntimeError, ValueError, FileNotFoundError, TimeoutError) as exc:
        safe = redact_text(str(exc), [args.source_url])
        print_json({"error": safe}, stream=sys.stderr)
        return 1


def build_manage_parser() -> argparse.ArgumentParser:
    """Build file-management commands separated from share management."""

    parser = argparse.ArgumentParser(description="Manage Yandex Disk resources")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    subparsers = parser.add_subparsers(dest="command", required=True)
    mkdir_parser = subparsers.add_parser("mkdir", help="Create a disk:/ or app:/ directory")
    add_common_auth(mkdir_parser)
    add_path_arg(mkdir_parser)

    delete_parser = subparsers.add_parser("delete", help="Delete a disk:/ or app:/ resource")
    add_common_auth(delete_parser)
    add_path_arg(delete_parser)
    delete_parser.add_argument("--permanently", action="store_true", help="Bypass Trash when supported")
    delete_parser.add_argument("--force-async", action="store_true", help="Request asynchronous deletion")

    for command in ("copy", "move"):
        subparser = subparsers.add_parser(command, help=f"{command.title()} a disk:/ or app:/ resource")
        add_common_auth(subparser)
        add_path_arg(subparser, option="--from-path", help_text="Source disk:/ or app:/ path")
        add_path_arg(subparser, help_text="Destination disk:/ or app:/ path")
        subparser.add_argument("--overwrite", action="store_true", help="Overwrite destination if it exists")
    return parser


def manage_main(argv: list[str] | None = None) -> int:
    """Run file-management commands against DiskWrite workflows."""

    parser = build_manage_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    disk = YandexDisk(account=args.account, data_dir=args.data_dir)
    try:
        if args.command == "mkdir":
            result = disk.ensure_dir(args.path)
        elif args.command == "delete":
            result = disk.delete_resource(args.path, permanently=args.permanently, force_async=args.force_async)
        elif args.command == "copy":
            result = disk.copy_resource(args.from_path, args.path, overwrite=args.overwrite)
        elif args.command == "move":
            result = disk.move_resource(args.from_path, args.path, overwrite=args.overwrite)
        else:
            parser.error(f"Unsupported command: {args.command}")
        print_json(result)
        return 0
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print_json({"error": str(exc)}, stream=sys.stderr)
        return 1


def build_disk_parser() -> argparse.ArgumentParser:
    """Build the canonical Disk command surface with scenario subcommands."""

    parser = argparse.ArgumentParser(description="Yandex Disk command facade")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("download", parents=[build_download_parser()], add_help=False)
    subparsers.add_parser("list", parents=[build_list_parser()], add_help=False)
    subparsers.add_parser("share", parents=[build_share_parser()], add_help=False)
    subparsers.add_parser("upload", parents=[build_upload_parser()], add_help=False)
    subparsers.add_parser("import-url", parents=[build_import_url_parser()], add_help=False)
    subparsers.add_parser("manage", parents=[build_manage_parser()], add_help=False)
    subparsers.add_parser("s3-upload", parents=[build_s3_parser()], add_help=False)
    return parser


def disk_main(argv: list[str] | None = None) -> int:
    """Dispatch the canonical Disk command facade to scenario handlers."""

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        return build_disk_parser().parse_args(argv)  # pragma: no cover - argparse exits
    command, rest = argv[0], argv[1:]
    handlers = {
        "download": download_main,
        "list": list_main,
        "share": share_main,
        "upload": upload_main,
        "import-url": import_url_main,
        "manage": manage_main,
        "s3-upload": s3_upload_main,
    }
    if command not in handlers:
        parser = build_disk_parser()
        parser.error(f"Unsupported command: {command}")
    return handlers[command](rest)
