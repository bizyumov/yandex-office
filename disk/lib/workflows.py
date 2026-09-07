#!/usr/bin/env python3
"""Shared Yandex Disk read, write, share, and materialization workflows.

This module contains reusable business workflows over the provider gateway in
``disk.lib.api``. It deliberately keeps CLI parsing elsewhere and composes
DiskRead, DiskWrite, and DiskShare into the public YandexDisk facade.
"""

import json
import logging
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import re
import time
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

try:
    import requests
except ImportError:
    print("Missing dependency: pip install requests", file=sys.stderr)
    sys.exit(1)

from disk.lib.api import DiskApi


logger = logging.getLogger("YandexDisk")

REDACTED_URL = "<redacted-url>"
PRIVATE_PATH_PREFIXES = ("disk:/", "app:/")
OPERATION_RE = re.compile(r"/operations/([^/?]+)")

SHARE_RIGHTS = {
    "read",
    "write",
    "read_without_download",
    "read_with_password",
    "read_with_password_without_download",
}
PASSWORD_RIGHTS = {
    "read_with_password",
    "read_with_password_without_download",
}
ACCESS_MODES = {"employees", "all"}


def redact_text(text: str, secrets) -> str:
    """Replace secret URL material (raw and percent-encoded) in a message."""

    out = str(text)
    for secret in secrets or ():
        raw = str(secret or "")
        if not raw:
            continue
        out = out.replace(raw, REDACTED_URL)
        out = out.replace(quote(raw, safe=""), REDACTED_URL)
    return out


def url_host(url: str) -> str:
    """Return only the host part of a URL for redaction-safe reporting."""

    return urlparse(str(url)).netloc


def is_private_disk_path(path: str) -> bool:
    """Identify authenticated Disk namespace paths before CLI dispatch."""

    return str(path).startswith(PRIVATE_PATH_PREFIXES)


def require_private_disk_path(path: str) -> None:
    """Reject unsupported path prefixes at the shared boundary."""

    if not is_private_disk_path(path):
        raise ValueError(f"Unsupported Disk path prefix: {path!r}")


def is_public_url(value: str) -> bool:
    """Identify public-link inputs without treating them as Disk paths."""

    parsed = urlparse(str(value))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_relative_member(rel: str) -> Path:
    """Validate one relative member path for safe local materialization.

    Rejects empty paths, absolute paths, and ``..`` traversal. Used by both
    public-folder materialization and private selected-set materialization so
    the safety logic stays shared across path surfaces.
    """

    raw = str(rel)
    if raw.startswith("/"):
        raise ValueError(f"Absolute member path rejected: {raw!r}")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts:
        raise ValueError(f"Empty relative member path rejected: {raw!r}")
    if ".." in parts:
        raise ValueError(f"Path traversal rejected in member path: {raw!r}")
    return Path(*parts)


def safe_local_name(name: str, *, fallback: str = "download") -> str:
    """Constrain provider names or overrides to a single local filename."""

    raw = str(name or "").strip() or fallback
    member = validate_relative_member(raw)
    if len(member.parts) != 1:
        raise ValueError(f"Unsafe local filename rejected: {raw!r}")
    return member.name


def safe_relative_path(remote_path: str, source_root: str) -> Path:
    """Return the member path of ``remote_path`` relative to ``source_root``.

    Both values are authenticated Disk paths (``disk:/...`` or ``app:/...``).
    Entries outside the source root, equal to the source root, or containing
    unsafe members are rejected.
    """

    raw_path = unquote(str(remote_path))
    raw_root = unquote(str(source_root)).rstrip("/")
    if not raw_root:
        raise ValueError("Source root must not be empty")
    if raw_path == raw_root:
        raise ValueError(
            f"Manifest entry equals the source root (expected a file under it): {raw_path!r}"
        )
    if not raw_path.startswith(raw_root + "/"):
        raise ValueError(
            f"Manifest entry outside source root {raw_root!r}: {raw_path!r}"
        )
    return validate_relative_member(raw_path[len(raw_root) + 1:])


def normalize_private_path(path: str) -> str:
    """Normalize disk:/ and app:/ paths while preserving their surface."""

    require_private_disk_path(path)
    scheme, rest = str(path).split(":", 1)
    parts = [part for part in rest.lstrip("/").split("/") if part not in ("", ".")]
    if ".." in parts:
        raise ValueError(f"Path traversal rejected in Disk path: {path!r}")
    return f"{scheme}:/" + "/".join(parts) if parts else f"{scheme}:/"


def surface_for_path(path: str) -> str:
    """Return the proof/evidence surface label for a Disk or public input."""

    if str(path).startswith("disk:/"):
        return "disk:/"
    if str(path).startswith("app:/"):
        return "app:/"
    if is_public_url(path):
        return "public-link"
    raise ValueError(f"Unsupported path surface: {path!r}")


def load_manifest_entries(manifest_path: str | Path) -> list[dict]:
    """Load selected-file manifest entries from a JSON array or JSONL file."""

    text = Path(manifest_path).read_text(encoding="utf-8")
    stripped = text.lstrip()
    if not stripped:
        raise ValueError(f"Manifest is empty: {manifest_path}")
    if stripped.startswith("["):
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("JSON manifest must be a list of entries")
        entries = data
    else:
        entries = [json.loads(line) for line in text.splitlines() if line.strip()]
    normalized: list[dict] = []
    for index, entry in enumerate(entries):
        if isinstance(entry, str):
            entry = {"path": entry}
        if not isinstance(entry, dict) or not str(entry.get("path", "")).strip():
            raise ValueError(f"Manifest entry {index} must provide a non-empty 'path'")
        normalized.append({"path": str(entry["path"]).strip()})
    return normalized


def normalize_resource(meta: dict, *, surface: str) -> dict:
    """Return stable machine-readable resource metadata."""

    return {
        "surface": surface,
        "name": meta.get("name"),
        "path": meta.get("path"),
        "type": meta.get("type"),
        "size": meta.get("size"),
        "mime_type": meta.get("mime_type"),
        "public_key": meta.get("public_key"),
        "public_url": meta.get("public_url"),
        "public_settings": meta.get("public_settings"),
    }


class DiskRead(DiskApi):
    """Read and materialization workflows shared by public links, disk:/, and app:/ paths."""

    def get_resource_meta(self, path: str) -> dict:
        """Get authenticated metadata for a Disk resource path."""
        return self.list_resource(path)


    def list_resource(
        self,
        path: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict:
        """Get authenticated metadata/listing for a Disk resource path."""
        path = normalize_private_path(path)
        endpoint = f"{self.api_base}/v1/disk/resources"
        logger.debug(f"GET {endpoint} auth=method-dispatch")
        if self._is_app_path(path):
            return self._api_get_resource_app_folder(endpoint, path, limit, offset)
        return self._api_get_resource_disk(endpoint, path, limit, offset)


    def iter_children(self, path: str, *, limit: int = 100) -> Iterable[dict]:
        """Yield direct children of a private Disk directory."""

        offset = 0
        while True:
            data = self.list_resource(path, limit=limit, offset=offset)
            embedded = data.get("_embedded") or {}
            items = embedded.get("items") or []
            for item in items:
                yield item
            total = int(embedded.get("total") or len(items) or 0)
            offset += len(items)
            if not items or offset >= total:
                break


    def list_tree(self, path: str, *, limit: int = 100, recursive: bool = False) -> list[dict]:
        """Return normalized child metadata for a private Disk folder."""

        root = normalize_private_path(path)
        surface = surface_for_path(root)
        result: list[dict] = []
        stack = [root]
        while stack:
            current = stack.pop()
            for item in self.iter_children(current, limit=limit):
                normalized = normalize_resource(item, surface=surface)
                result.append(normalized)
                if recursive and item.get("type") == "dir" and item.get("path"):
                    stack.append(str(item["path"]))
        return result


    def get_private_download_link(self, path: str) -> str:
        """Resolve an authenticated download href without exposing token logic."""

        path = normalize_private_path(path)
        endpoint = f"{self.api_base}/v1/disk/resources/download"
        logger.debug(f"GET {endpoint} auth=method-dispatch")
        if self._is_app_path(path):
            data = self._api_get_private_download_link_app_folder(endpoint, path)
        else:
            data = self._api_get_private_download_link_disk(endpoint, path)
        href = data.get("href")
        if not href:
            raise RuntimeError("Disk download URL response did not include href")
        return str(href)


    def _download_href_to_file(self, href: str, filepath: Path) -> Path:
        """Stream a provider-issued href into a caller-selected safe path."""

        filepath.parent.mkdir(parents=True, exist_ok=True)
        resp = self.session.get(href, stream=True)
        resp.raise_for_status()
        with open(filepath, "wb") as handle:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        return filepath


    def download_private_file(
        self,
        path: str,
        *,
        output_dir: str = ".",
        filename: str | None = None,
        overwrite: bool = False,
    ) -> dict:
        """Download one authenticated disk:/ or app:/ file by path."""

        path = normalize_private_path(path)
        meta = self.get_resource_meta(path)
        if meta.get("type") == "dir":
            raise ValueError(f"Private download path is a directory, not a file: {path}")
        local_name = safe_local_name(filename or meta.get("name") or Path(path).name)
        filepath = Path(output_dir).expanduser().resolve() / local_name
        if filepath.exists() and not overwrite:
            raise FileExistsError(f"Output file already exists: {filepath}")
        href = self.get_private_download_link(path)
        self._download_href_to_file(href, filepath)
        return {
            "surface": surface_for_path(path),
            "path": path,
            "filepath": str(filepath),
            "name": local_name,
            "size": filepath.stat().st_size,
            "mime_type": meta.get("mime_type"),
            "downloaded": True,
        }


    def materialize_selected_private(
        self,
        *,
        manifest_path: str | Path,
        source_root: str,
        output_dir: str,
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> dict:
        """Materialize selected authenticated files from a JSON/JSONL manifest."""

        source_root = normalize_private_path(source_root)
        entries = load_manifest_entries(manifest_path)
        base = Path(output_dir).expanduser().resolve()
        planned: list[dict] = []
        for entry in entries:
            remote_path = normalize_private_path(entry["path"])
            if surface_for_path(remote_path) != surface_for_path(source_root):
                raise ValueError(
                    f"Manifest entry surface does not match source root: {remote_path!r}"
                )
            rel = safe_relative_path(remote_path, source_root)
            target = base / rel
            meta = self.get_resource_meta(remote_path)
            if meta.get("type") == "dir":
                raise ValueError(f"Manifest entry is a directory, not a file: {remote_path}")
            if target.exists() and not overwrite:
                raise FileExistsError(f"Output file already exists: {target}")
            planned.append(
                {
                    "surface": surface_for_path(remote_path),
                    "path": remote_path,
                    "relative_path": str(rel),
                    "output_path": str(target),
                    "size": meta.get("size"),
                    "mime_type": meta.get("mime_type"),
                }
            )

        if dry_run:
            return {
                "surface": surface_for_path(source_root),
                "source_root": source_root,
                "output_dir": str(base),
                "dry_run": True,
                "files": planned,
            }

        downloaded: list[dict] = []
        for item in planned:
            href = self.get_private_download_link(item["path"])
            filepath = self._download_href_to_file(href, Path(item["output_path"]))
            downloaded.append({**item, "downloaded": True, "actual_size": filepath.stat().st_size})
        return {
            "surface": surface_for_path(source_root),
            "source_root": source_root,
            "output_dir": str(base),
            "dry_run": False,
            "files": downloaded,
        }


    def get_public_meta(
        self,
        public_url: str,
        anonymous: bool = False,
        *,
        path: str = "",
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict:
        """Get metadata for a public file or directory.

        GET /v1/disk/public/resources?public_key={url}

        GH41 treats this as a public method, so OAuth is not sent even when a
        token exists on the client. The ``anonymous`` flag is retained for CLI
        compatibility and no longer changes token selection.

        Returns dict with: name, size, mime_type, created, modified, public_url, etc.
        """
        data = self._api_get_public_meta(public_url, path, limit, offset)

        return {
            "name": data.get("name", ""),
            "size": data.get("size", 0),
            "mime_type": data.get("mime_type", ""),
            "created": data.get("created", ""),
            "modified": data.get("modified", ""),
            "public_url": data.get("public_url", public_url),
            "type": data.get("type", "file"),
            "path": data.get("path", ""),
            "_embedded": data.get("_embedded"),
        }


    def get_download_link(
        self,
        public_url: str,
        path: str = "",
        anonymous: bool = False,
    ) -> str:
        """Get direct download URL for a public resource.

        GET /v1/disk/public/resources/download?public_key={url}

        For directories, pass path= to specify the file within.
        GH41 treats this as a public method, so OAuth is not sent.
        Returns the direct download href.
        """
        data = self._api_get_public_download_link(public_url, path)
        return data["href"]


    def download(
        self,
        public_url: str,
        output_dir: str = ".",
        filename: str | None = None,
        path: str = "",
        anonymous: bool = False,
        overwrite: bool = False,
    ) -> Path:
        """Download a public file to local disk.

        Args:
            public_url: yadi.sk or disk.yandex.ru share link
            output_dir: directory to save into
            filename: override output filename (default: use original name)
            path: for directories, the file path within
            anonymous: compatibility flag; public API calls are already tokenless

        Returns:
            Path to the downloaded file.
        """
        # Get metadata for filename
        if not filename:
            meta = self.get_public_meta(public_url, anonymous=anonymous, path=path)
            filename = meta["name"] or "download"
        filename = safe_local_name(filename)

        # Get direct download link
        href = self.get_download_link(public_url, path=path, anonymous=anonymous)

        # Download
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        filepath = out_path / filename
        if filepath.exists() and not overwrite:
            raise FileExistsError(f"Output file already exists: {filepath}")

        logger.info(f"Downloading {filename} to {filepath}")

        resp = self.session.get(href, stream=True)
        resp.raise_for_status()

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        size = filepath.stat().st_size
        logger.info(f"Downloaded {size} bytes to {filepath}")

        return filepath


    def _iter_public_dir_items(
        self,
        public_url: str,
        *,
        path: str = "",
        anonymous: bool = False,
        limit: int = 100,
    ) -> Iterable[dict]:
        """Page through public-folder children by provider relative path."""

        offset = 0
        while True:
            meta = self.get_public_meta(
                public_url,
                anonymous=anonymous,
                path=path,
                limit=limit,
                offset=offset,
            )
            embedded = meta.get("_embedded") or {}
            items = embedded.get("items") or []
            for item in items:
                yield item
            total = int(embedded.get("total") or len(items) or 0)
            offset += len(items)
            if not items or offset >= total:
                break


    def materialize_public_folder(
        self,
        public_url: str,
        *,
        output_dir: str = ".",
        flatten_single_root: bool = False,
        anonymous: bool = False,
        overwrite: bool = False,
    ) -> dict:
        """Download public-folder members while preserving provider names."""

        meta = self.get_public_meta(public_url, anonymous=anonymous)
        if meta.get("type") != "dir":
            filepath = self.download(
                public_url,
                output_dir=output_dir,
                anonymous=anonymous,
                overwrite=overwrite,
            )
            return {
                "surface": "public-link",
                "resource_type": "file",
                "folder_mode_applied": False,
                "requested_materialize_dir": True,
                "requested_flatten_single_root": bool(flatten_single_root),
                "filepath": str(filepath),
                "name": filepath.name,
                "size": filepath.stat().st_size,
            }

        folder_name = safe_local_name(meta.get("name") or "public-folder", fallback="public-folder")
        output_base = Path(output_dir).expanduser().resolve()
        root = output_base if flatten_single_root else output_base / folder_name
        planned: list[tuple[str, Path, dict]] = []
        stack: list[tuple[str, Path]] = [("", Path())]
        while stack:
            public_path, rel_root = stack.pop()
            for item in self._iter_public_dir_items(public_url, path=public_path, anonymous=anonymous):
                item_name = safe_local_name(item.get("name") or "download")
                item_rel = rel_root / item_name
                item_public_path = str(item.get("path") or "").strip()
                if item.get("type") == "dir":
                    stack.append((item_public_path, item_rel))
                    continue
                rel = validate_relative_member(str(item_rel).replace(os.sep, "/"))
                target = root / rel
                if target.exists() and not overwrite:
                    raise FileExistsError(f"Output file already exists: {target}")
                planned.append((item_public_path, target, item))

        files: list[dict] = []
        for item_public_path, target, item in planned:
            href = self.get_download_link(public_url, path=item_public_path, anonymous=anonymous)
            self._download_href_to_file(href, target)
            files.append(
                {
                    "path": item_public_path,
                    "output_path": str(target),
                    "name": target.name,
                    "size": target.stat().st_size,
                    "mime_type": item.get("mime_type"),
                }
            )
        return {
            "surface": "public-link",
            "resource_type": "dir",
            "folder_mode_applied": True,
            "flatten_single_root": bool(flatten_single_root),
            "output_root": str(root),
            "name": folder_name,
            "files": files,
        }


    def download_with_meta(
        self,
        public_url: str,
        output_dir: str = ".",
        filename: str | None = None,
        anonymous: bool = False,
        *,
        materialize_dir: bool = False,
        flatten_single_root: bool = False,
        overwrite: bool = False,
    ) -> dict:
        """Download file and return metadata dict.

        Convenience method for use by other skills (e.g. telemost).

        Returns:
            dict with: filepath, name, size, mime_type, public_url
        """
        meta = self.get_public_meta(public_url, anonymous=anonymous)

        if meta.get("type") == "dir" and (materialize_dir or flatten_single_root):
            return self.materialize_public_folder(
                public_url,
                output_dir=output_dir,
                flatten_single_root=flatten_single_root,
                anonymous=anonymous,
                overwrite=overwrite,
            )

        if not filename:
            filename = meta["name"] or "download"

        filepath = self.download(
            public_url,
            output_dir=output_dir,
            filename=filename,
            anonymous=anonymous,
            overwrite=overwrite,
        )

        return {
            "surface": "public-link",
            "resource_type": meta.get("type", "file"),
            "folder_mode_applied": False,
            "requested_materialize_dir": bool(materialize_dir),
            "requested_flatten_single_root": bool(flatten_single_root),
            "filepath": str(filepath),
            "name": meta["name"],
            "size": filepath.stat().st_size,
            "mime_type": meta["mime_type"],
            "public_url": public_url,
        }




class DiskWrite(DiskApi):
    """Write, manage, and URL-import workflows shared across Disk path surfaces."""

    @staticmethod
    def _parent_dir_paths(path: str) -> list[str]:
        """Compute same-surface parent paths for direct upload preparation."""

        if ":" not in path:
            raise ValueError(f"Unsupported Disk path: {path}")
        scheme, remainder = path.split(":", 1)
        parts = [part for part in remainder.lstrip("/").split("/") if part]
        if len(parts) <= 1:
            return []
        parents: list[str] = []
        current: list[str] = []
        for part in parts[:-1]:
            current.append(part)
            parents.append(f"{scheme}:/" + "/".join(current))
        return parents


    def ensure_dir(self, path: str) -> dict:
        """Create one disk:/ or app:/ directory idempotently."""

        endpoint = f"{self.api_base}/v1/disk/resources"
        logger.debug(f"PUT {endpoint} auth=method-dispatch")
        if self._is_app_path(path):
            return self._api_put_resource_app_folder(endpoint, path)
        return self._api_put_resource_disk(endpoint, path)


    def ensure_parent_dirs(self, path: str) -> list[dict]:
        """Create parent directories for upload without touching the file leaf."""

        return [self.ensure_dir(parent_path) for parent_path in self._parent_dir_paths(path)]


    def delete_resource(self, path: str, *, permanently: bool = False, force_async: bool = False) -> dict:
        """Delete one resource through the path surface's write method id."""

        path = normalize_private_path(path)
        endpoint = f"{self.api_base}/v1/disk/resources"
        logger.debug(f"DELETE {endpoint} auth=method-dispatch")
        if self._is_app_path(path):
            data, status = self._api_delete_resource_app_folder(endpoint, path, permanently, force_async)
        else:
            data, status = self._api_delete_resource_disk(endpoint, path, permanently, force_async)
        return {
            "surface": surface_for_path(path),
            "path": path,
            "deleted": status in (200, 202, 204),
            "status_code": status,
            "operation_id": self._operation_id_from_payload(data),
        }


    def copy_resource(self, from_path: str, path: str, *, overwrite: bool = False) -> dict:
        """Copy a resource, rejecting unproven cross-surface operations."""

        return self._copy_or_move_resource("copy", from_path, path, overwrite=overwrite)


    def move_resource(self, from_path: str, path: str, *, overwrite: bool = False) -> dict:
        """Move a resource, rejecting unproven cross-surface operations."""

        return self._copy_or_move_resource("move", from_path, path, overwrite=overwrite)


    def _copy_or_move_resource(
        self,
        operation: str,
        from_path: str,
        path: str,
        *,
        overwrite: bool = False,
    ) -> dict:
        """Share one copy/move code path while preserving method dispatch."""

        from_path = normalize_private_path(from_path)
        path = normalize_private_path(path)
        if surface_for_path(from_path) != surface_for_path(path):
            raise ValueError("copy/move source and destination must use the same path surface")
        endpoint = f"{self.api_base}/v1/disk/resources/{operation}"
        logger.debug(f"POST {endpoint} auth=method-dispatch")
        if operation == "copy":
            if self._is_app_path(path):
                data = self._api_copy_resource_app_folder(endpoint, from_path, path, overwrite)
            else:
                data = self._api_copy_resource_disk(endpoint, from_path, path, overwrite)
        elif self._is_app_path(path):
            data = self._api_move_resource_app_folder(endpoint, from_path, path, overwrite)
        else:
            data = self._api_move_resource_disk(endpoint, from_path, path, overwrite)
        return {
            "surface": surface_for_path(path),
            "from_path": from_path,
            "path": path,
            operation: True,
            "operation_id": self._operation_id_from_payload(data),
        }


    def get_upload_link(self, path: str, overwrite: bool = False) -> dict:
        """Request a direct upload href for the selected private path surface."""

        path = normalize_private_path(path)
        endpoint = f"{self.api_base}/v1/disk/resources/upload"
        logger.debug(f"GET {endpoint} auth=method-dispatch")
        if self._is_app_path(path):
            return self._api_get_upload_link_app_folder(endpoint, path, overwrite)
        return self._api_get_upload_link_disk(endpoint, path, overwrite)


    def upload_file(
        self,
        local_path: str | Path,
        remote_path: str,
        *,
        overwrite: bool = False,
        create_parents: bool = True,
    ) -> dict:
        """Upload a local file through the provider's one-shot upload href."""

        local_file = Path(local_path).expanduser().resolve()
        if not local_file.exists() or not local_file.is_file():
            raise ValueError(f"Local file not found: {local_file}")

        created_dirs: list[dict] = []
        if create_parents:
            created_dirs = self.ensure_parent_dirs(remote_path)

        try:
            upload_meta = self.get_upload_link(remote_path, overwrite=overwrite)
        except RuntimeError as exc:
            if create_parents and "Disk resource not found" in str(exc):
                raise RuntimeError(
                    f"Disk path does not exist after parent creation attempt: {remote_path}"
                ) from exc
            raise

        href = upload_meta.get("href")
        if not href:
            raise RuntimeError("Disk upload URL response did not include href")

        with open(local_file, "rb") as handle:
            resp = self.session.request("PUT", href, data=handle)
        try:
            resp.raise_for_status()
        except requests.HTTPError as err:
            status = err.response.status_code if err.response is not None else None
            message = err.response.text if err.response is not None else str(err)
            if status == 409:
                raise RuntimeError(
                    f"Disk upload conflict: target already exists at {remote_path}"
                ) from err
            raise RuntimeError(f"Disk upload error {status}: {message}") from err

        meta = self.get_resource_meta(remote_path)
        return {
            "local_path": str(local_file),
            "remote_path": remote_path,
            "path": meta.get("path", remote_path),
            "name": meta.get("name", local_file.name),
            "size": meta.get("size", local_file.stat().st_size),
            "mime_type": meta.get("mime_type"),
            "created_dirs": created_dirs,
            "uploaded": True,
        }


    def upload_and_publish(
        self,
        local_path: str | Path,
        remote_path: str,
        *,
        overwrite: bool = False,
        create_parents: bool = True,
        access: str | None = None,
        org_id: int | str | None = None,
        rights: str | None = None,
        password: str | None = None,
        available_until: int | None = None,
        user_ids: list[int | str] | None = None,
        group_ids: list[int | str] | None = None,
        department_ids: list[int | str] | None = None,
    ) -> dict:
        """Compose upload plus publish into the standard attachment handoff."""

        upload_result = self.upload_file(
            local_path,
            remote_path,
            overwrite=overwrite,
            create_parents=create_parents,
        )
        share_result = self.publish_file(
            path=remote_path,
            access=access,
            org_id=org_id,
            rights=rights,
            password=password,
            available_until=available_until,
            user_ids=user_ids,
            group_ids=group_ids,
            department_ids=department_ids,
        )
        result = dict(upload_result)
        result.update(
            {
                "public_key": share_result.get("public_key"),
                "public_url": share_result.get("public_url"),
                "public_settings": share_result.get("public_settings"),
            }
        )
        if share_result.get("public_url"):
            result["attachment"] = {
                "fileName": result.get("name") or safe_local_name(str(remote_path).rsplit("/", 1)[-1]),
                "url": share_result["public_url"],
                "size": result.get("size"),
            }
        return result


    @staticmethod
    def _operation_id_from_payload(data: dict | None) -> str | None:
        """Extract provider operation ids from async operation href payloads."""

        if not isinstance(data, dict):
            return None
        href = str(data.get("href") or "")
        match = OPERATION_RE.search(href)
        return match.group(1) if match else None


    def upload_from_url(
        self,
        *,
        source_url: str,
        remote_path: str,
        overwrite: bool = False,
        disable_redirects: bool = False,
        wait: bool = False,
        timeout_seconds: int = 7200,
        poll_seconds: int = 10,
        verify_size: int | None = None,
    ) -> dict:
        """Ask Disk to import a URL into disk:/ or app:/ through managed auth."""

        remote_path = normalize_private_path(remote_path)
        endpoint = f"{self.api_base}/v1/disk/resources/upload"
        logger.debug(f"POST {endpoint} auth=method-dispatch source_url={REDACTED_URL}")
        if self._is_app_path(remote_path):
            data = self._api_upload_from_url_app_folder(
                endpoint,
                source_url,
                remote_path,
                overwrite,
                disable_redirects,
            )
        else:
            data = self._api_upload_from_url_disk(
                endpoint,
                source_url,
                remote_path,
                overwrite,
                disable_redirects,
            )
        operation_id = self._operation_id_from_payload(data)
        operation_status = None
        if wait and operation_id:
            operation_status = self.wait_operation(
                operation_id,
                surface=surface_for_path(remote_path),
                timeout_seconds=timeout_seconds,
                poll_seconds=poll_seconds,
            )
        meta = self.get_resource_meta(remote_path) if wait else {}
        actual_size = meta.get("size")
        if verify_size is not None and actual_size is not None and int(actual_size) != int(verify_size):
            raise RuntimeError(
                f"Disk metadata size mismatch for {remote_path}: expected={verify_size} actual={actual_size}"
            )
        return {
            "surface": surface_for_path(remote_path),
            "path": remote_path,
            "source_url_host": url_host(source_url),
            "source_url_redacted": True,
            "operation_id": operation_id,
            "operation_status": operation_status,
            "size": actual_size,
            "imported": bool(wait and (not operation_id or operation_status == "success")) if wait else None,
        }


    def get_operation_status(self, operation_id: str, *, surface: str = "disk:/") -> dict:
        """Poll one operation with the method id matching its origin surface."""

        endpoint = f"{self.api_base}/v1/disk/operations/{operation_id}"
        logger.debug(f"GET {endpoint} auth=method-dispatch")
        if surface == "app:/":
            return self._api_get_operation_app_folder(endpoint)
        return self._api_get_operation_disk(endpoint)


    def wait_operation(
        self,
        operation_id: str,
        *,
        surface: str = "disk:/",
        timeout_seconds: int = 7200,
        poll_seconds: int = 10,
    ) -> str:
        """Wait for Disk async completion with bounded polling."""

        deadline = time.monotonic() + int(timeout_seconds)
        last_status = "unknown"
        while time.monotonic() < deadline:
            data = self.get_operation_status(operation_id, surface=surface)
            last_status = str(data.get("status") or "unknown")
            if last_status == "success":
                return last_status
            if last_status == "failed":
                raise RuntimeError(f"Disk operation failed: {data}")
            time.sleep(max(1, int(poll_seconds)))
        raise TimeoutError(f"Disk operation timed out: {operation_id} last_status={last_status}")



class DiskShare(DiskApi):
    """Share-link policy workflows for publish, update, inspect, and revoke operations."""

    @staticmethod
    def _parse_id_list(values: list[int | str] | None) -> list[str]:
        """Normalize optional share target id lists from CLI/API callers."""

        if not values:
            return []
        parsed = []
        for value in values:
            raw = str(value).strip()
            if raw:
                parsed.append(raw)
        return parsed


    def _resolve_org_id(self, access: str | None, org_id: int | str | None) -> str | None:
        """Require org id only when the employees access macro needs it."""

        if access != "employees":
            return str(org_id).strip() if org_id is not None and str(org_id).strip() else None
        if org_id is not None and str(org_id).strip():
            return str(org_id).strip()
        raise ValueError("employees access requires org_id")


    @staticmethod
    def _to_int_if_possible(value: str | None) -> int | str | None:
        """Preserve string ids unless the provider expects numeric ids."""

        if value is None:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return raw


    @staticmethod
    def _normalize_available_until(value: int | None) -> int | None:
        """Accept either a future timestamp or a positive TTL in seconds."""

        if value is None:
            return None
        normalized = int(value)
        if normalized <= 0:
            raise ValueError("available_until must be a positive integer")
        if normalized <= int(time.time()):
            return int(time.time()) + normalized
        return normalized


    def _build_share_payload(
        self,
        *,
        access: str | None = None,
        org_id: int | str | None = None,
        rights: str | None = None,
        password: str | None = None,
        available_until: int | None = None,
        user_ids: list[int | str] | None = None,
        group_ids: list[int | str] | None = None,
        department_ids: list[int | str] | None = None,
    ) -> dict:
        """Construct provider share settings with validation before network IO."""

        if access is not None and access not in ACCESS_MODES:
            raise ValueError(f"Unsupported access mode: {access}")
        if rights is not None and rights not in SHARE_RIGHTS:
            raise ValueError(f"Unsupported rights mode: {rights}")
        if password and rights not in PASSWORD_RIGHTS:
            raise ValueError("password is allowed only with password-protected rights")
        if rights in PASSWORD_RIGHTS and not password:
            raise ValueError("password-protected rights require password")
        normalized_available_until = self._normalize_available_until(available_until)

        payload: dict[str, object] = {}
        accesses: list[dict[str, object]] = []

        resolved_org_id = self._resolve_org_id(access, org_id)
        if access:
            access_entry: dict[str, object] = {"macros": [access]}
            if resolved_org_id:
                access_entry["org_id"] = self._to_int_if_possible(resolved_org_id)
            if rights:
                access_entry["rights"] = [rights]
            accesses.append(access_entry)

        for key, raw_values in (
            ("user_ids", user_ids),
            ("group_ids", group_ids),
            ("department_ids", department_ids),
        ):
            values = self._parse_id_list(raw_values)
            if not values:
                continue
            typed_values: list[int | str]
            if key in {"group_ids", "department_ids"}:
                typed_values = [self._to_int_if_possible(value) for value in values]
            else:
                typed_values = values
            entry: dict[str, object] = {key: typed_values}
            if rights:
                entry["rights"] = [rights]
            accesses.append(entry)

        public_settings: dict[str, object] = {}
        if password:
            public_settings["password"] = password
        if normalized_available_until is not None:
            public_settings["available_until"] = normalized_available_until
        if accesses:
            public_settings["accesses"] = accesses
        if public_settings:
            payload["public_settings"] = public_settings
        return payload


    @staticmethod
    def _normalize_share_response(path: str, data: dict) -> dict:
        """Project inconsistent provider share responses into stable JSON."""

        public_settings = data.get("public_settings") or {}
        if not public_settings and data.get("accesses"):
            public_settings = {"accesses": data.get("accesses", [])}
        return {
            "path": path,
            "public_key": data.get("public_key"),
            "public_url": data.get("public_url"),
            "public_settings": public_settings,
        }


    def _finalize_publish_result(
        self,
        *,
        path: str,
        initial_data: dict,
    ) -> dict:
        """Refresh publish results when the provider omits share details."""

        result = self._normalize_share_response(path, initial_data)
        needs_refresh = (
            not result.get("public_key")
            or not result.get("public_url")
            or not result.get("public_settings")
        )
        if needs_refresh:
            refreshed = self.get_share_info(path)
            result = dict(result)
            result.update({k: v for k, v in refreshed.items() if v})
            if "public_settings" not in result:
                result["public_settings"] = refreshed.get("public_settings", {})
        return result


    def get_share_info(self, path: str) -> dict:
        """Get current share metadata for a Disk resource path."""
        meta = self.get_resource_meta(path)
        return self._normalize_share_response(path, meta)


    def publish_file(
        self,
        *,
        path: str,
        access: str | None = None,
        org_id: int | str | None = None,
        rights: str | None = None,
        password: str | None = None,
        available_until: int | None = None,
        user_ids: list[int | str] | None = None,
        group_ids: list[int | str] | None = None,
        department_ids: list[int | str] | None = None,
    ) -> dict:
        """Publish a Disk resource and configure share access."""
        endpoint = f"{self.api_base}/v1/disk/resources/publish"
        payload = self._build_share_payload(
            access=access,
            org_id=org_id,
            rights=rights,
            password=password,
            available_until=available_until,
            user_ids=user_ids,
            group_ids=group_ids,
            department_ids=department_ids,
        )
        logger.debug(f"PUT {endpoint} auth=method-dispatch")
        if self._is_app_path(path):
            data = self._api_publish_app_folder(endpoint, path, payload)
        else:
            data = self._api_publish_disk(endpoint, path, payload)
        return self._finalize_publish_result(path=path, initial_data=data)


    def update_share_settings(
        self,
        *,
        path: str,
        access: str | None = None,
        org_id: int | str | None = None,
        rights: str | None = None,
        password: str | None = None,
        available_until: int | None = None,
        user_ids: list[int | str] | None = None,
        group_ids: list[int | str] | None = None,
        department_ids: list[int | str] | None = None,
    ) -> dict:
        """Update existing share settings for a published resource."""
        current = self.get_share_info(path)
        current_public_settings = current.get("public_settings") or {}
        if not current.get("public_key") and not current_public_settings.get("accesses"):
            raise RuntimeError(f"Disk resource is not currently published: {path}")
        endpoint = f"{self.api_base}/v1/disk/resources/publish"
        payload = self._build_share_payload(
            access=access,
            org_id=org_id,
            rights=rights,
            password=password,
            available_until=available_until,
            user_ids=user_ids,
            group_ids=group_ids,
            department_ids=department_ids,
        )
        logger.debug(f"PUT {endpoint} auth=method-dispatch")
        if self._is_app_path(path):
            data = self._api_publish_app_folder(endpoint, path, payload)
        else:
            data = self._api_publish_disk(endpoint, path, payload)
        return self._finalize_publish_result(path=path, initial_data=data)


    def unpublish_file(self, path: str) -> dict:
        """Revoke a published share link."""
        endpoint = f"{self.api_base}/v1/disk/resources/unpublish"
        logger.debug(f"PUT {endpoint} auth=method-dispatch")
        if self._is_app_path(path):
            self._api_unpublish_app_folder(endpoint, path)
        else:
            self._api_unpublish_disk(endpoint, path)
        return {"path": path, "unpublished": True}



class YandexDisk(DiskRead, DiskWrite, DiskShare):
    """Facade that composes Disk read, write, and share workflows."""

    pass
