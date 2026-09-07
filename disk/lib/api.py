#!/usr/bin/env python3
"""Decorated provider gateway for Yandex Disk API calls.

This module owns provider endpoints, method ids, OAuth scope dispatch, request
shapes, and disk:/ versus app:/ API selection. Business workflows live in
``disk.lib.workflows`` so decorated provider plumbing stays isolated.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import logging

try:
    import requests
except ImportError:
    print("Missing dependency: pip install requests", file=sys.stderr)
    sys.exit(1)

from common.api import YandexApiContext, request_json, yandex_api_method
from common.config import load_runtime_context


logger = logging.getLogger("YandexDisk")

API_BASE = "https://cloud-api.yandex.net"


class DiskApi:
    """Provider gateway for decorated Yandex Disk API calls and surface dispatch."""

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


    @staticmethod
    def _is_app_path(path: str) -> bool:
        """Return True when a Disk path targets the app-folder namespace."""

        return str(path).startswith("app:")


    @yandex_api_method("disk.resources.get.disk", one_of=["cloud_api:disk.read"])
    def _api_get_resource_disk(
        self,
        ctx: YandexApiContext,
        endpoint: str,
        path: str,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict:
        """GET /v1/disk/resources for disk:/ paths."""

        params: dict[str, str | int] = {"path": path}
        if limit is not None:
            params["limit"] = int(limit)
        if offset is not None:
            params["offset"] = int(offset)
        return request_json(ctx, "GET", endpoint, params=params)


    @yandex_api_method("disk.resources.get.app_folder", one_of=["cloud_api:disk.app_folder"])
    def _api_get_resource_app_folder(
        self,
        ctx: YandexApiContext,
        endpoint: str,
        path: str,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict:
        """GET /v1/disk/resources for app:/ paths."""

        params: dict[str, str | int] = {"path": path}
        if limit is not None:
            params["limit"] = int(limit)
        if offset is not None:
            params["offset"] = int(offset)
        return request_json(ctx, "GET", endpoint, params=params)


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


    @yandex_api_method("disk.resources.unpublish.put.disk", one_of=["cloud_api:disk.write"])
    def _api_unpublish_disk(self, ctx: YandexApiContext, endpoint: str, path: str) -> dict:
        """PUT /v1/disk/resources/unpublish for disk:/ paths."""

        return request_json(ctx, "PUT", endpoint, params={"path": path})


    @yandex_api_method("disk.resources.unpublish.put.app_folder", one_of=["cloud_api:disk.app_folder"])
    def _api_unpublish_app_folder(self, ctx: YandexApiContext, endpoint: str, path: str) -> dict:
        """PUT /v1/disk/resources/unpublish for app:/ paths."""

        return request_json(ctx, "PUT", endpoint, params={"path": path})


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


    @yandex_api_method("disk.resources.download.get.disk", one_of=["cloud_api:disk.read"])
    def _api_get_private_download_link_disk(
        self,
        ctx: YandexApiContext,
        endpoint: str,
        path: str,
    ) -> dict:
        """GET /v1/disk/resources/download for disk:/ paths."""

        return request_json(ctx, "GET", endpoint, params={"path": path})


    @yandex_api_method("disk.resources.download.get.app_folder", one_of=["cloud_api:disk.app_folder"])
    def _api_get_private_download_link_app_folder(
        self,
        ctx: YandexApiContext,
        endpoint: str,
        path: str,
    ) -> dict:
        """GET /v1/disk/resources/download for app:/ paths."""

        return request_json(ctx, "GET", endpoint, params={"path": path})


    @yandex_api_method("disk.resources.delete.disk", one_of=["cloud_api:disk.write"])
    def _api_delete_resource_disk(
        self,
        ctx: YandexApiContext,
        endpoint: str,
        path: str,
        permanently: bool,
        force_async: bool,
    ) -> tuple[dict | None, int]:
        """DELETE /v1/disk/resources for disk:/ paths with status preservation."""

        return request_json(
            ctx,
            "DELETE",
            endpoint,
            expected_statuses=(200, 202, 204),
            return_status=True,
            params={
                "path": path,
                "permanently": str(bool(permanently)).lower(),
                "force_async": str(bool(force_async)).lower(),
            },
        )


    @yandex_api_method("disk.resources.delete.app_folder", one_of=["cloud_api:disk.app_folder"])
    def _api_delete_resource_app_folder(
        self,
        ctx: YandexApiContext,
        endpoint: str,
        path: str,
        permanently: bool,
        force_async: bool,
    ) -> tuple[dict | None, int]:
        """DELETE /v1/disk/resources for app:/ paths with app-folder scope."""

        return request_json(
            ctx,
            "DELETE",
            endpoint,
            expected_statuses=(200, 202, 204),
            return_status=True,
            params={
                "path": path,
                "permanently": str(bool(permanently)).lower(),
                "force_async": str(bool(force_async)).lower(),
            },
        )


    @yandex_api_method("disk.resources.copy.post.disk", all_of=["cloud_api:disk.read", "cloud_api:disk.write"])
    def _api_copy_resource_disk(self, ctx: YandexApiContext, endpoint: str, from_path: str, path: str, overwrite: bool) -> dict:
        """POST /v1/disk/resources/copy for same-surface disk:/ copies."""

        return request_json(ctx, "POST", endpoint, expected_statuses=(200, 201, 202), params={"from": from_path, "path": path, "overwrite": str(bool(overwrite)).lower()})


    @yandex_api_method("disk.resources.copy.post.app_folder", one_of=["cloud_api:disk.app_folder"])
    def _api_copy_resource_app_folder(self, ctx: YandexApiContext, endpoint: str, from_path: str, path: str, overwrite: bool) -> dict:
        """POST /v1/disk/resources/copy for same-surface app:/ copies."""

        return request_json(ctx, "POST", endpoint, expected_statuses=(200, 201, 202), params={"from": from_path, "path": path, "overwrite": str(bool(overwrite)).lower()})


    @yandex_api_method("disk.resources.move.post.disk", all_of=["cloud_api:disk.read", "cloud_api:disk.write"])
    def _api_move_resource_disk(self, ctx: YandexApiContext, endpoint: str, from_path: str, path: str, overwrite: bool) -> dict:
        """POST /v1/disk/resources/move for same-surface disk:/ moves."""

        return request_json(ctx, "POST", endpoint, expected_statuses=(200, 201, 202), params={"from": from_path, "path": path, "overwrite": str(bool(overwrite)).lower()})


    @yandex_api_method("disk.resources.move.post.app_folder", one_of=["cloud_api:disk.app_folder"])
    def _api_move_resource_app_folder(self, ctx: YandexApiContext, endpoint: str, from_path: str, path: str, overwrite: bool) -> dict:
        """POST /v1/disk/resources/move for same-surface app:/ moves."""

        return request_json(ctx, "POST", endpoint, expected_statuses=(200, 201, 202), params={"from": from_path, "path": path, "overwrite": str(bool(overwrite)).lower()})


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


    @yandex_api_method("disk.resources.upload.post.disk", one_of=["cloud_api:disk.write"])
    def _api_upload_from_url_disk(
        self,
        ctx: YandexApiContext,
        endpoint: str,
        source_url: str,
        path: str,
        overwrite: bool,
        disable_redirects: bool,
    ) -> dict:
        """POST /v1/disk/resources/upload?url=... for disk:/ URL imports."""

        return request_json(
            ctx,
            "POST",
            endpoint,
            expected_statuses=(200, 202),
            params={
                "path": path,
                "url": source_url,
                "overwrite": str(bool(overwrite)).lower(),
                "disable_redirects": str(bool(disable_redirects)).lower(),
            },
        )


    @yandex_api_method("disk.resources.upload.post.app_folder", one_of=["cloud_api:disk.app_folder"])
    def _api_upload_from_url_app_folder(
        self,
        ctx: YandexApiContext,
        endpoint: str,
        source_url: str,
        path: str,
        overwrite: bool,
        disable_redirects: bool,
    ) -> dict:
        """POST /v1/disk/resources/upload?url=... for app:/ URL imports."""

        return request_json(
            ctx,
            "POST",
            endpoint,
            expected_statuses=(200, 202),
            params={
                "path": path,
                "url": source_url,
                "overwrite": str(bool(overwrite)).lower(),
                "disable_redirects": str(bool(disable_redirects)).lower(),
            },
        )


    @yandex_api_method("disk.operations.get.disk", one_of=["cloud_api:disk.app_folder", "cloud_api:disk.info", "cloud_api:disk.read", "cloud_api:disk.write"])
    def _api_get_operation_disk(self, ctx: YandexApiContext, endpoint: str) -> dict:
        """GET /v1/disk/operations/{id} for disk:/-originated async work."""

        return request_json(ctx, "GET", endpoint)


    @yandex_api_method("disk.operations.get.app_folder", one_of=["cloud_api:disk.app_folder", "cloud_api:disk.info", "cloud_api:disk.read", "cloud_api:disk.write"])
    def _api_get_operation_app_folder(self, ctx: YandexApiContext, endpoint: str) -> dict:
        """GET /v1/disk/operations/{id} for app:/-originated async work."""

        return request_json(ctx, "GET", endpoint)


    @yandex_api_method("disk.public.resources.get", public=True)
    def _api_get_public_meta(
        self,
        ctx: YandexApiContext,
        public_url: str,
        path: str = "",
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict:
        """GET /v1/disk/public/resources without OAuth."""

        endpoint = f"{self.api_base}/v1/disk/public/resources"
        logger.debug(f"GET {endpoint} auth=no")
        params: dict[str, str | int] = {"public_key": public_url}
        if path:
            params["path"] = path
        if limit is not None:
            params["limit"] = int(limit)
        if offset is not None:
            params["offset"] = int(offset)
        return request_json(ctx, "GET", endpoint, params=params)


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
