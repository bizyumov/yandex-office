#!/usr/bin/env python3
"""
Yandex Disk public file downloader.

Downloads files from Yandex Disk using public share links (yadi.sk).
Uses the Yandex Disk REST API v1.

API docs: https://yandex.ru/dev/disk-api/doc/ru/concepts/quickstart
Playground: https://yandex.ru/dev/disk/poligon/

Usage:
    python download.py "https://yadi.sk/d/abc123" --output ./downloads/
    python download.py "https://disk.yandex.ru/d/abc123" --output ./downloads/
"""

import sys
import json
import argparse
import logging
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("Missing dependency: pip install requests", file=sys.stderr)
    sys.exit(1)


logger = logging.getLogger("YandexDisk")

API_BASE = "https://cloud-api.yandex.net"

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.api import (
    YandexApiContext,
    digest_legacy_disk_token_env as digest_legacy_disk_token_env_ctx,
    request_json,
    yandex_api_method,
)
from common.config import load_runtime_context

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


class YandexDisk:
    """Client for Yandex Disk REST API."""

    def __init__(
        self,
        account: str | None = None,
        data_dir: str | None = None,
    ):
        """Initialize Disk client state without resolving tokens.

        Token selection is owned by the method decorators. Public methods run
        tokenless; non-public methods require an account unless the central
        dispatcher can infer the only token file.
        """
        self.runtime = load_runtime_context(
            __file__,
            data_dir_override=data_dir,
            require_external_data_dir=data_dir is not None,
        )
        self._config = self.runtime.config
        self._data_dir = self.runtime.data_dir
        self.api_base = self._config.get("urls", {}).get("disk_api", API_BASE)
        self.account = account
        self.session = requests.Session()

    def _api_context(self) -> YandexApiContext:
        """Build the shared API context used by decorated Disk methods.
        """

        return YandexApiContext(
            account=self.account,
            data_dir=self._data_dir,
            config=self._config,
            session=self.session,
        )

    def digest_legacy_disk_token_env(self) -> None:
        """Import legacy Disk env auth into managed auth when present."""

        digest_legacy_disk_token_env_ctx(self._api_context())

    @staticmethod
    def _parse_id_list(values: list[int | str] | None) -> list[str]:
        if not values:
            return []
        parsed = []
        for value in values:
            raw = str(value).strip()
            if raw:
                parsed.append(raw)
        return parsed

    def _resolve_org_id(self, access: str | None, org_id: int | str | None) -> str | None:
        if access != "employees":
            return str(org_id).strip() if org_id is not None and str(org_id).strip() else None
        if org_id is not None and str(org_id).strip():
            return str(org_id).strip()
        raise ValueError("employees access requires org_id")

    @staticmethod
    def _to_int_if_possible(value: str | None) -> int | str | None:
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

    def get_resource_meta(self, path: str) -> dict:
        """Get authenticated metadata for a Disk resource path."""
        endpoint = f"{self.api_base}/v1/disk/resources"
        logger.debug(f"GET {endpoint} auth=method-dispatch")
        if self._is_app_path(path):
            return self._api_get_resource_app_folder(endpoint, path)
        return self._api_get_resource_disk(endpoint, path)

    @staticmethod
    def _is_app_path(path: str) -> bool:
        """Return True when a Disk path targets the app-folder namespace."""

        return str(path).startswith("app:")

    @yandex_api_method("disk.resources.get.disk", one_of=["cloud_api:disk.read"])
    def _api_get_resource_disk(self, ctx: YandexApiContext, endpoint: str, path: str) -> dict:
        """GET /v1/disk/resources for disk:/ paths."""

        return request_json(ctx, "GET", endpoint, params={"path": path})

    @yandex_api_method("disk.resources.get.app_folder", one_of=["cloud_api:disk.app_folder"])
    def _api_get_resource_app_folder(self, ctx: YandexApiContext, endpoint: str, path: str) -> dict:
        """GET /v1/disk/resources for app:/ paths."""

        return request_json(ctx, "GET", endpoint, params={"path": path})

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

    @yandex_api_method("disk.resources.publish.put.disk", one_of=["cloud_api:disk.write"])
    def _api_publish_disk(
        self,
        ctx: YandexApiContext,
        endpoint: str,
        path: str,
        payload: dict,
    ) -> dict:
        """PUT /v1/disk/resources/publish for disk:/ paths."""

        return request_json(
            ctx,
            "PUT",
            endpoint,
            params={"path": path, "allow_address_access": "true"},
            json=payload or None,
        )

    @yandex_api_method("disk.resources.publish.put.app_folder", one_of=["cloud_api:disk.app_folder"])
    def _api_publish_app_folder(
        self,
        ctx: YandexApiContext,
        endpoint: str,
        path: str,
        payload: dict,
    ) -> dict:
        """PUT /v1/disk/resources/publish for app:/ paths."""

        return request_json(
            ctx,
            "PUT",
            endpoint,
            params={"path": path, "allow_address_access": "true"},
            json=payload or None,
        )

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

    @yandex_api_method("disk.resources.unpublish.put.disk", one_of=["cloud_api:disk.write"])
    def _api_unpublish_disk(self, ctx: YandexApiContext, endpoint: str, path: str) -> dict:
        """PUT /v1/disk/resources/unpublish for disk:/ paths."""

        return request_json(ctx, "PUT", endpoint, params={"path": path})

    @yandex_api_method("disk.resources.unpublish.put.app_folder", one_of=["cloud_api:disk.app_folder"])
    def _api_unpublish_app_folder(self, ctx: YandexApiContext, endpoint: str, path: str) -> dict:
        """PUT /v1/disk/resources/unpublish for app:/ paths."""

        return request_json(ctx, "PUT", endpoint, params={"path": path})

    @staticmethod
    def _parent_dir_paths(path: str) -> list[str]:
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
        endpoint = f"{self.api_base}/v1/disk/resources"
        logger.debug(f"PUT {endpoint} auth=method-dispatch")
        if self._is_app_path(path):
            return self._api_put_resource_app_folder(endpoint, path)
        return self._api_put_resource_disk(endpoint, path)

    @yandex_api_method("disk.resources.put.disk", one_of=["cloud_api:disk.write"])
    def _api_put_resource_disk(self, ctx: YandexApiContext, endpoint: str, path: str) -> dict:
        """PUT /v1/disk/resources for disk:/ paths."""

        _, status_code = request_json(
            ctx,
            "PUT",
            endpoint,
            expected_statuses=(200, 201, 204, 409),
            return_status=True,
            params={"path": path},
        )
        return {"path": path, "created": status_code != 409}

    @yandex_api_method("disk.resources.put.app_folder", one_of=["cloud_api:disk.app_folder"])
    def _api_put_resource_app_folder(self, ctx: YandexApiContext, endpoint: str, path: str) -> dict:
        """PUT /v1/disk/resources for app:/ paths."""

        _, status_code = request_json(
            ctx,
            "PUT",
            endpoint,
            expected_statuses=(200, 201, 204, 409),
            return_status=True,
            params={"path": path},
        )
        return {"path": path, "created": status_code != 409}

    def ensure_parent_dirs(self, path: str) -> list[dict]:
        return [self.ensure_dir(parent_path) for parent_path in self._parent_dir_paths(path)]

    def get_upload_link(self, path: str, overwrite: bool = False) -> dict:
        endpoint = f"{self.api_base}/v1/disk/resources/upload"
        logger.debug(f"GET {endpoint} auth=method-dispatch")
        if self._is_app_path(path):
            return self._api_get_upload_link_app_folder(endpoint, path, overwrite)
        return self._api_get_upload_link_disk(endpoint, path, overwrite)

    @yandex_api_method("disk.resources.upload.get.disk", one_of=["cloud_api:disk.write"])
    def _api_get_upload_link_disk(
        self,
        ctx: YandexApiContext,
        endpoint: str,
        path: str,
        overwrite: bool,
    ) -> dict:
        """GET /v1/disk/resources/upload for disk:/ paths."""

        return request_json(
            ctx,
            "GET",
            endpoint,
            params={"path": path, "overwrite": str(bool(overwrite)).lower()},
        )

    @yandex_api_method("disk.resources.upload.get.app_folder", one_of=["cloud_api:disk.app_folder"])
    def _api_get_upload_link_app_folder(
        self,
        ctx: YandexApiContext,
        endpoint: str,
        path: str,
        overwrite: bool,
    ) -> dict:
        """GET /v1/disk/resources/upload for app:/ paths."""

        return request_json(
            ctx,
            "GET",
            endpoint,
            params={"path": path, "overwrite": str(bool(overwrite)).lower()},
        )

    def upload_file(
        self,
        local_path: str | Path,
        remote_path: str,
        *,
        overwrite: bool = False,
        create_parents: bool = True,
    ) -> dict:
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
        return result

    def get_public_meta(self, public_url: str, anonymous: bool = False) -> dict:
        """Get metadata for a public file or directory.

        GET /v1/disk/public/resources?public_key={url}

        GH41 treats this as a public method, so OAuth is not sent even when a
        token exists on the client. The ``anonymous`` flag is retained for CLI
        compatibility and no longer changes token selection.

        Returns dict with: name, size, mime_type, created, modified, public_url, etc.
        """
        data = self._api_get_public_meta(public_url)

        return {
            "name": data.get("name", ""),
            "size": data.get("size", 0),
            "mime_type": data.get("mime_type", ""),
            "created": data.get("created", ""),
            "modified": data.get("modified", ""),
            "public_url": data.get("public_url", public_url),
            "type": data.get("type", "file"),
            "path": data.get("path", ""),
        }

    @yandex_api_method("disk.public.resources.get", public=True)
    def _api_get_public_meta(self, ctx: YandexApiContext, public_url: str) -> dict:
        """GET /v1/disk/public/resources without OAuth."""

        endpoint = f"{self.api_base}/v1/disk/public/resources"
        logger.debug(f"GET {endpoint} auth=no")
        return request_json(ctx, "GET", endpoint, params={"public_key": public_url})

    @yandex_api_method("disk.public.resources.download.get", public=True)
    def _api_get_public_download_link(
        self,
        ctx: YandexApiContext,
        public_url: str,
        path: str = "",
    ) -> dict:
        """GET /v1/disk/public/resources/download without OAuth."""

        params = {"public_key": public_url}
        if path:
            params["path"] = path
        endpoint = f"{self.api_base}/v1/disk/public/resources/download"
        logger.debug(f"GET {endpoint} auth=no")
        return request_json(ctx, "GET", endpoint, params=params)

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
            meta = self.get_public_meta(public_url, anonymous=anonymous)
            filename = meta["name"] or "download"

        # Get direct download link
        href = self.get_download_link(public_url, path=path, anonymous=anonymous)

        # Download
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        filepath = out_path / filename

        logger.info(f"Downloading {filename} to {filepath}")

        resp = self.session.get(href, stream=True)
        resp.raise_for_status()

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        size = filepath.stat().st_size
        logger.info(f"Downloaded {size} bytes to {filepath}")

        return filepath

    def download_with_meta(
        self,
        public_url: str,
        output_dir: str = ".",
        filename: str | None = None,
        anonymous: bool = False,
    ) -> dict:
        """Download file and return metadata dict.

        Convenience method for use by other skills (e.g. telemost).

        Returns:
            dict with: filepath, name, size, mime_type, public_url
        """
        meta = self.get_public_meta(public_url, anonymous=anonymous)

        if not filename:
            filename = meta["name"] or "download"

        filepath = self.download(
            public_url, output_dir=output_dir, filename=filename, anonymous=anonymous
        )

        return {
            "filepath": str(filepath),
            "name": meta["name"],
            "size": filepath.stat().st_size,
            "mime_type": meta["mime_type"],
            "public_url": public_url,
        }


def main():
    parser = argparse.ArgumentParser(
        description="Download files from Yandex Disk share links",
    )
    parser.add_argument("url", help="Public yadi.sk or disk.yandex.ru link")
    parser.add_argument(
        "--output", "-o", default=".", help="Output directory (default: current)"
    )
    parser.add_argument(
        "--filename", "-f", help="Override output filename"
    )
    parser.add_argument(
        "--account", "-a", help="Account name — resolves to data/auth/{account}.token"
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Explicit Yandex data directory override for non-workspace execution",
    )
    parser.add_argument(
        "--meta", action="store_true", help="Print file metadata as JSON"
    )
    parser.add_argument(
        "--anonymous",
        action="store_true",
        help="Deprecated compatibility flag; public API methods are tokenless",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    disk = YandexDisk(
        account=args.account,
        data_dir=args.data_dir,
    )
    try:
        disk.digest_legacy_disk_token_env()
    except Exception:
        pass

    if args.meta:
        meta = disk.get_public_meta(args.url, anonymous=args.anonymous)
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return

    result = disk.download_with_meta(
        args.url, output_dir=args.output, filename=args.filename, anonymous=args.anonymous
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
