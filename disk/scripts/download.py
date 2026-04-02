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

import os
import sys
import json
import argparse
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

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

from common.auth import default_scopes, load_token_file, resolve_token
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
DISK_READ_SCOPES = default_scopes("disk", "read")
DISK_WRITE_SCOPES = default_scopes("disk", "write")


class YandexDisk:
    """Client for Yandex Disk REST API."""

    def __init__(
        self,
        token: str | None = None,
        token_file: str | None = None,
        account: str | None = None,
        auth_dir: str | None = None,
        required_scopes: list[str] | None = None,
    ):
        """Initialize with token resolution chain.

        Priority: token > token_file > account > YANDEX_DISK_TOKEN env > None (public only)

        If auth_dir is None, resolves from shared config's data_dir.
        """
        self.runtime = load_runtime_context(__file__)
        self._config = self.runtime.config
        self._data_dir = self.runtime.data_dir
        self.api_base = self._config.get("urls", {}).get("disk_api", API_BASE)
        self.account = account
        self._required_scopes = list(required_scopes or DISK_READ_SCOPES)
        self._explicit_token = token is not None
        self._token_file_path = Path(token_file).resolve() if token_file else None

        resolved_auth_dir = Path(auth_dir).resolve() if auth_dir else None
        self._auth_dir = resolved_auth_dir

        self.token = token
        if not self.token and token_file:
            self.token = self._read_token(Path(token_file))
        if not self.token and account:
            if resolved_auth_dir is None:
                try:
                    self.token = self._resolve_account_token(self._required_scopes)
                except Exception as exc:
                    logger.debug(str(exc))
            else:
                self.token = self._read_token(resolved_auth_dir / f"{account}.token")
        if not self.token:
            self.token = os.getenv("YANDEX_DISK_TOKEN")
        self.session = requests.Session()
        if self.token:
            self._set_session_token(self.token)

    def _link_access_session(self, anonymous: bool = False) -> requests.Session:
        """Return the session used for public-link endpoints.

        By default we use the authenticated session when a token is available,
        even for public-looking links. Anonymous access is opt-in and should be
        used only to verify anonymous reachability or when explicitly requested.
        """
        if not anonymous:
            return self.session
        return requests.Session()

    def _request_json(self, method: str, endpoint: str, **kwargs) -> dict:
        resp = self.session.request(method, endpoint, **kwargs)
        try:
            resp.raise_for_status()
        except requests.HTTPError as err:
            status = err.response.status_code if err.response is not None else None
            message = err.response.text if err.response is not None else str(err)
            if status == 401:
                raise RuntimeError("Disk authentication failed: invalid or expired token") from err
            if status == 403:
                raise RuntimeError("Disk access denied: token lacks required permissions") from err
            if status == 404:
                raise RuntimeError(f"Disk resource not found: {message}") from err
            raise RuntimeError(f"Disk API error {status}: {message}") from err
        if resp.content:
            return resp.json()
        return {}

    def _set_session_token(self, token: str) -> None:
        self.token = token
        self.session.headers["Authorization"] = f"OAuth {token}"

    def _resolve_account_token(self, required_scopes: list[str]) -> str:
        if not self.account:
            raise RuntimeError("Disk account is required for token resolution")
        token_info = resolve_token(
            account=self.account,
            skill="disk",
            data_dir=self._data_dir,
            config=self._config,
            required_scopes=required_scopes,
        )
        self._set_session_token(token_info.token)
        return token_info.token

    def _ensure_disk_token(
        self,
        *,
        required_scopes: list[str],
        operation: str,
    ) -> None:
        if self.token and (
            self._explicit_token
            or self._token_file_path
            or self._auth_dir is not None
        ):
            return
        if self.account and self._auth_dir is None:
            try:
                self._resolve_account_token(required_scopes)
                return
            except RuntimeError as exc:
                raise RuntimeError(
                    f"Disk authentication failed for {operation}: {exc}"
                ) from exc
        if self.token:
            return
        raise RuntimeError(
            f"Disk authentication is required for {operation}. "
            "Set YANDEX_DISK_TOKEN or provide --account/--token-file."
        )

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
        token_path = self._token_file_path
        if token_path is None and self._auth_dir is not None and self.account:
            token_path = self._auth_dir / f"{self.account}.token"
        if token_path is None and self.account:
            token_path = self._data_dir / "auth" / f"{self.account}.token"
        if token_path is None:
            raise ValueError("employees access requires org_id or token metadata")
        if not token_path.exists():
            raise ValueError("employees access requires org_id")
        token_data = load_token_file(token_path)
        token_org_id = token_data.get("org_id")
        if token_org_id is None or not str(token_org_id).strip():
            raise ValueError("employees access requires org_id")
        return str(token_org_id).strip()

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
        self._ensure_disk_token(
            required_scopes=DISK_WRITE_SCOPES,
            operation="resource metadata",
        )
        endpoint = f"{self.api_base}/v1/disk/resources"
        logger.debug(f"GET {endpoint} auth={'yes' if self.token else 'no'}")
        return self._request_json("GET", endpoint, params={"path": path})

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
        self._ensure_disk_token(
            required_scopes=DISK_WRITE_SCOPES,
            operation="share management",
        )
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
        logger.debug(f"PUT {endpoint} auth={'yes' if self.token else 'no'}")
        data = self._request_json(
            "PUT",
            endpoint,
            params={"path": path, "allow_address_access": "true"},
            json=payload or None,
        )
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
        self._ensure_disk_token(
            required_scopes=DISK_WRITE_SCOPES,
            operation="share management",
        )
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
        logger.debug(f"PUT {endpoint} auth={'yes' if self.token else 'no'}")
        data = self._request_json(
            "PUT",
            endpoint,
            params={"path": path, "allow_address_access": "true"},
            json=payload or None,
        )
        return self._finalize_publish_result(path=path, initial_data=data)

    def unpublish_file(self, path: str) -> dict:
        """Revoke a published share link."""
        self._ensure_disk_token(
            required_scopes=DISK_WRITE_SCOPES,
            operation="share management",
        )
        endpoint = f"{self.api_base}/v1/disk/resources/unpublish"
        logger.debug(f"PUT {endpoint} auth={'yes' if self.token else 'no'}")
        self._request_json("PUT", endpoint, params={"path": path})
        return {"path": path, "unpublished": True}

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
        self._ensure_disk_token(
            required_scopes=DISK_WRITE_SCOPES,
            operation="directory creation",
        )
        endpoint = f"{self.api_base}/v1/disk/resources"
        logger.debug(f"PUT {endpoint} auth={'yes' if self.token else 'no'}")
        resp = self.session.request("PUT", endpoint, params={"path": path})
        if resp.status_code == 409:
            return {"path": path, "created": False}
        try:
            resp.raise_for_status()
        except requests.HTTPError as err:
            status = err.response.status_code if err.response is not None else None
            message = err.response.text if err.response is not None else str(err)
            if status == 403:
                raise RuntimeError(
                    "Disk access denied: token lacks required permissions for directory creation"
                ) from err
            raise RuntimeError(f"Disk directory create error {status}: {message}") from err
        return {"path": path, "created": True}

    def ensure_parent_dirs(self, path: str) -> list[dict]:
        return [self.ensure_dir(parent_path) for parent_path in self._parent_dir_paths(path)]

    def get_upload_link(self, path: str, overwrite: bool = False) -> dict:
        self._ensure_disk_token(
            required_scopes=DISK_WRITE_SCOPES,
            operation="upload",
        )
        endpoint = f"{self.api_base}/v1/disk/resources/upload"
        logger.debug(f"GET {endpoint} auth={'yes' if self.token else 'no'}")
        return self._request_json(
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
        self._ensure_disk_token(
            required_scopes=DISK_WRITE_SCOPES,
            operation="upload",
        )
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

    @staticmethod
    def _read_token(path: Path) -> str | None:
        """Read disk token from account token file.

        Token format: {"email": "...", "token.disk": "y0_..."}
        """
        if not path.exists():
            logger.debug(f"Token file not found: {path}")
            return None
        try:
            data = load_token_file(path)
            if data.get("token.disk"):
                return data.get("token.disk")
            return None
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to read token from {path}: {e}")
            return None

    @staticmethod
    def _looks_like_yandex_share(public_url: str) -> bool:
        parsed = urlparse(public_url)
        host = (parsed.netloc or "").lower()
        return "yadi.sk" in host or "disk.yandex." in host

    def _raise_with_context(
        self,
        err: requests.HTTPError,
        public_url: str,
        force_auth: bool = False,
        anonymous: bool = False,
    ) -> None:
        status = err.response.status_code if err.response is not None else None
        if status == 404 and self._looks_like_yandex_share(public_url):
            if anonymous:
                hint = (
                    "404 from Yandex Disk public API under anonymous access. "
                    "This can be expected for organization-only shares. "
                    "Retry with OAuth unless you are explicitly testing anonymous access."
                )
            else:
                hint = (
                    "404 from Yandex Disk API. Telemost recordings and organization-only "
                    "shares may require OAuth authentication even for public-looking links. "
                    "Set YANDEX_DISK_TOKEN or provide --account/--token-file."
                )
            if force_auth and not self.token:
                hint = (
                    "OAuth is required (--force-auth), but no token is configured. "
                    "Set YANDEX_DISK_TOKEN or provide --account/--token-file."
                )
            raise RuntimeError(hint) from err
        raise err

    def get_public_meta(self, public_url: str, anonymous: bool = False) -> dict:
        """Get metadata for a public file or directory.

        GET /v1/disk/public/resources?public_key={url}

        Uses OAuth by default when a token is available. Pass anonymous=True
        only when you explicitly need to test anonymous reachability.

        Returns dict with: name, size, mime_type, created, modified, public_url, etc.
        """
        session = self._link_access_session(anonymous=anonymous)
        endpoint = f"{self.api_base}/v1/disk/public/resources"
        logger.debug(f"GET {endpoint} auth={'yes' if (self.token and not anonymous) else 'no'}")
        resp = session.get(endpoint, params={"public_key": public_url})
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            self._raise_with_context(e, public_url, anonymous=anonymous)
        data = resp.json()

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

    def get_download_link(
        self,
        public_url: str,
        path: str = "",
        anonymous: bool = False,
    ) -> str:
        """Get direct download URL for a public resource.

        GET /v1/disk/public/resources/download?public_key={url}

        For directories, pass path= to specify the file within.
        Uses OAuth by default when a token is available.
        Returns the direct download href.
        """
        params = {"public_key": public_url}
        if path:
            params["path"] = path

        session = self._link_access_session(anonymous=anonymous)
        endpoint = f"{self.api_base}/v1/disk/public/resources/download"
        logger.debug(f"GET {endpoint} auth={'yes' if (self.token and not anonymous) else 'no'}")
        resp = session.get(endpoint, params=params)
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            self._raise_with_context(e, public_url, anonymous=anonymous)
        return resp.json()["href"]

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
            anonymous: use anonymous link access instead of OAuth

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
        "--token-file", help="Path to token JSON file ({account}.token)"
    )
    parser.add_argument(
        "--account", "-a", help="Account name — resolves to data/auth/{account}.token"
    )
    parser.add_argument(
        "--auth-dir", default=None, help="Auth directory (default: from config)"
    )
    parser.add_argument(
        "--meta", action="store_true", help="Print file metadata as JSON"
    )
    parser.add_argument(
        "--force-auth",
        action="store_true",
        help="Require OAuth token and fail if no token is configured",
    )
    parser.add_argument(
        "--anonymous",
        action="store_true",
        help="Use anonymous link access instead of OAuth; intended only for explicit anonymous-access checks",
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
        token_file=args.token_file,
        account=args.account,
        auth_dir=args.auth_dir,
    )
    if args.force_auth and args.anonymous:
        print("--force-auth and --anonymous are mutually exclusive.", file=sys.stderr)
        sys.exit(2)
    if args.force_auth and not disk.token:
        print(
            "OAuth is required (--force-auth), but no token was found. "
            "Set YANDEX_DISK_TOKEN or provide --account/--token-file.",
            file=sys.stderr,
        )
        sys.exit(2)

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
