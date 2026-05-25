"""Yandex Telemost API client."""

from __future__ import annotations

from contextlib import contextmanager
import os
import re
from pathlib import Path
import sys
from typing import Any

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.api import (
    BlockedYandexMethodError,
    TokenConfigError,
    YandexApiContext,
    YandexApiError,
    request_json,
    yandex_api_method,
)
from common.config import load_runtime_context

DEFAULT_API_BASE = "https://cloud-api.yandex.net/v1/telemost-api"
VALID_ACCESS_LEVELS = {"PUBLIC", "ORGANIZATION"}
VALID_WAITING_ROOM_LEVELS = {"PUBLIC", "ORGANIZATION", "ADMINS"}
VALID_ORG_ROLES = {"OWNER", "INTERNAL_COHOST", "INTERNAL_MEMBER"}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UNSET = object()


class TelemostError(RuntimeError):
    """Structured Telemost API failure."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        payload = {"error": str(self)}
        payload.update(self.details)
        return payload


class YandexTelemostClient:
    """Client for Yandex Telemost conference management."""

    def __init__(
        self,
        account: str,
        data_dir: str | Path | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.account = account
        self.runtime = load_runtime_context(
            __file__,
            data_dir_override=data_dir,
            require_agent_config=True,
            require_external_data_dir=True,
        )
        self.data_dir = Path(data_dir).resolve() if data_dir else self.runtime.data_dir
        self.config = self.runtime.config
        self.api_base = self.config.get("urls", {}).get("telemost_api", DEFAULT_API_BASE).rstrip("/")
        self.config.setdefault("urls", {}).setdefault("telemost_api", self.api_base)
        self.session = session or requests.Session()

    def _api_context(self) -> YandexApiContext:
        """Build the shared GH41 API context for Telemost calls."""

        return YandexApiContext(
            account=self.account,
            data_dir=self.data_dir,
            config=self.config,
            session=self.session,
        )

    @staticmethod
    def _telemost_error(exc: YandexApiError) -> TelemostError:
        """Map central provider errors into the Telemost business exception."""

        details = {
            "status_code": exc.status_code,
            "response": exc.payload if exc.payload is not None else exc.message,
        }
        if exc.status_code in (401, 403):
            return TelemostError("Telemost API access denied", **details)
        if exc.status_code == 402:
            return TelemostError("Telemost live stream requires a paid Yandex 360 tariff", **details)
        if exc.status_code == 404:
            return TelemostError("Telemost conference not found", **details)
        return TelemostError("Telemost API request failed", **details)

    @contextmanager
    def _telemost_errors(self):
        """Map central auth/API exceptions while keeping API calls explicit."""
        try:
            yield
        except YandexApiError as exc:
            raise self._telemost_error(exc) from exc
        except (BlockedYandexMethodError, TokenConfigError) as exc:
            raise TelemostError(str(exc)) from exc

    @yandex_api_method("telemost.conferences.create.post", one_of=["telemost-api:conferences.create"])
    def _api_create_conference(self, ctx: YandexApiContext, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /conferences."""

        return request_json(
            ctx,
            "POST",
            ctx.url("telemost_api", "/conferences"),
            expected_statuses=(201,),
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=30,
        ) or {}

    @yandex_api_method("telemost.conferences.get", one_of=["telemost-api:conferences.read"])
    def _api_get_conference(self, ctx: YandexApiContext, conference_id: str) -> dict[str, Any]:
        """GET /conferences/{id}."""

        return request_json(
            ctx,
            "GET",
            ctx.url("telemost_api", f"/conferences/{conference_id}"),
            expected_statuses=(200,),
            timeout=30,
        ) or {}

    @yandex_api_method("telemost.conferences.patch", one_of=["telemost-api:conferences.update"])
    def _api_patch_conference(
        self,
        ctx: YandexApiContext,
        conference_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        """PATCH /conferences/{id}."""

        return request_json(
            ctx,
            "PATCH",
            ctx.url("telemost_api", f"/conferences/{conference_id}"),
            expected_statuses=(200,),
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )

    @yandex_api_method("telemost.conferences.cohosts.get", one_of=["telemost-api:conferences.read"])
    def _api_get_cohosts(self, ctx: YandexApiContext, conference_id: str) -> dict[str, Any]:
        """GET /conferences/{id}/cohosts."""

        return request_json(
            ctx,
            "GET",
            ctx.url("telemost_api", self._cohosts_path(conference_id)),
            expected_statuses=(200,),
            timeout=30,
        ) or {}

    @yandex_api_method("telemost.conferences.cohosts.put", one_of=["telemost-api:conferences.update"])
    def _api_put_cohosts(
        self,
        ctx: YandexApiContext,
        conference_id: str,
        payload: dict[str, Any],
    ) -> None:
        """PUT /conferences/{id}/cohosts."""

        request_json(
            ctx,
            "PUT",
            ctx.url("telemost_api", self._cohosts_path(conference_id)),
            expected_statuses=(204,),
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )

    @yandex_api_method("telemost.organizations.settings.get", one_of=["telemost-api:conferences.read"])
    def _api_get_org_settings(self, ctx: YandexApiContext, org_id: int | str) -> dict[str, Any]:
        """GET /organizations/{org_id}/settings."""

        return request_json(
            ctx,
            "GET",
            ctx.url("telemost_api", f"/organizations/{org_id}/settings"),
            expected_statuses=(200,),
            timeout=30,
        ) or {}

    @yandex_api_method("telemost.organizations.settings.put", one_of=["telemost-api:conferences.update"])
    def _api_put_org_settings(
        self,
        ctx: YandexApiContext,
        org_id: int | str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """PUT /organizations/{org_id}/settings."""

        return request_json(
            ctx,
            "PUT",
            ctx.url("telemost_api", f"/organizations/{org_id}/settings"),
            expected_statuses=(200,),
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=30,
        ) or {}

    @staticmethod
    def _validate_access_level(access_level: str | None) -> str | None:
        if access_level is None:
            return None
        normalized = access_level.strip().upper()
        if normalized not in VALID_ACCESS_LEVELS:
            raise ValueError(
                f"Invalid access_level {access_level!r}; expected one of {sorted(VALID_ACCESS_LEVELS)}"
            )
        return normalized

    @staticmethod
    def _validate_waiting_room_level(waiting_room_level: str | None) -> str | None:
        if waiting_room_level is None:
            return None
        normalized = waiting_room_level.strip().upper()
        if normalized not in VALID_WAITING_ROOM_LEVELS:
            raise ValueError(
                "Invalid waiting_room_level "
                f"{waiting_room_level!r}; expected one of {sorted(VALID_WAITING_ROOM_LEVELS)}"
            )
        return normalized

    @staticmethod
    def _normalize_cohosts(cohosts: list[str] | None) -> list[str] | None:
        if cohosts is None:
            return None
        normalized: list[str] = []
        for email in cohosts:
            value = str(email).strip().lower()
            if not value:
                continue
            if not _EMAIL_RE.match(value):
                raise ValueError(f"Invalid cohost email: {email!r}")
            normalized.append(value)
        deduped = []
        seen: set[str] = set()
        for email in normalized:
            if email not in seen:
                seen.add(email)
                deduped.append(email)
        return deduped

    def _normalize_live_stream(
        self,
        live_stream: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if live_stream is None:
            return None
        payload = dict(live_stream)
        access_level = self._validate_access_level(payload.get("access_level") or "PUBLIC")
        normalized: dict[str, Any] = {"access_level": access_level}
        title = payload.get("title")
        if title is not None:
            title = str(title).strip()
            if not title:
                raise ValueError("Live stream title must be non-empty when provided")
            normalized["title"] = title
        description = payload.get("description")
        if description is not None:
            description = str(description).strip()
            if not description:
                raise ValueError("Live stream description must be non-empty when provided")
            normalized["description"] = description
        return normalized

    def _conference_payload(
        self,
        *,
        access_level: str | None = None,
        waiting_room_level: str | None = None,
        live_stream: dict[str, Any] | None = None,
        cohosts: list[str] | object = _UNSET,
        include_cohosts: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        normalized_access = self._validate_access_level(access_level)
        normalized_waiting = self._validate_waiting_room_level(waiting_room_level)
        normalized_live_stream = self._normalize_live_stream(live_stream)

        if normalized_access is not None:
            payload["access_level"] = normalized_access
        if normalized_waiting is not None:
            payload["waiting_room_level"] = normalized_waiting
        if normalized_live_stream is not None:
            payload["live_stream"] = normalized_live_stream
        if include_cohosts and cohosts is not _UNSET:
            normalized_cohosts = self._normalize_cohosts(cohosts)
            payload["cohosts"] = [{"email": email} for email in normalized_cohosts or []]
        return payload

    @staticmethod
    def _normalize_conference(
        conference: dict[str, Any],
        *,
        cohosts: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized = {
            "id": conference.get("id"),
            "join_url": conference.get("join_url"),
            "access_level": conference.get("access_level"),
            "waiting_room_level": conference.get("waiting_room_level"),
            "sip_uri_meeting": conference.get("sip_uri_meeting"),
            "sip_uri_telemost": conference.get("sip_uri_telemost"),
            "sip_id": conference.get("sip_id"),
            "live_stream": conference.get("live_stream"),
            "cohosts": cohosts,
        }
        return normalized

    def _normalize_write_conference(
        self,
        conference: dict[str, Any],
        *,
        payload: dict[str, Any],
        cohosts: list[str] | None = None,
        conference_id: str | None = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_conference(conference, cohosts=cohosts)
        if normalized["id"] is None:
            normalized["id"] = conference_id
        for field in ("access_level", "waiting_room_level", "live_stream"):
            if normalized.get(field) is None and payload.get(field) is not None:
                normalized[field] = payload[field]
        return normalized

    def _cohosts_path(self, conference_id: str) -> str:
        return f"/conferences/{conference_id}/cohosts"

    @staticmethod
    def _resolve_org_id(org_id: int | str | None) -> int:
        """Normalize an explicit organization ID for organization settings."""

        if org_id is not None:
            return int(org_id)
        raise TelemostError("Organization ID is required; provide --org-id")

    @staticmethod
    def _normalize_role_list(roles: list[str] | None) -> list[str] | None:
        if roles is None:
            return None
        normalized: list[str] = []
        for role in roles:
            value = str(role).strip().upper()
            if not value:
                continue
            if value not in VALID_ORG_ROLES:
                raise ValueError(
                    f"Invalid organization role {role!r}; expected one of {sorted(VALID_ORG_ROLES)}"
                )
            if value not in normalized:
                normalized.append(value)
        return normalized

    @staticmethod
    def _normalize_org_settings_payload(payload: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        waiting_fields = {
            "waiting_room_level_adhoc",
            "waiting_room_level_calendar",
        }
        role_fields = {
            "cloud_recording_email_receivers",
            "summarization_email_receivers",
            "cloud_recording_allowed_roles",
            "summarization_allowed_roles",
        }
        for field, value in payload.items():
            if value is None:
                continue
            if field in waiting_fields:
                actual = value.get("value") if isinstance(value, dict) else value
                normalized[field] = {
                    "value": YandexTelemostClient._validate_waiting_room_level(actual)
                }
            elif field in role_fields:
                actual = value.get("value") if isinstance(value, dict) else value
                if not isinstance(actual, list):
                    raise ValueError(f"{field} must be a list of organization roles")
                normalized[field] = {
                    "value": YandexTelemostClient._normalize_role_list(actual) or []
                }
            else:
                normalized[field] = value
        return normalized

    def build_org_settings_payload(
        self,
        *,
        file_payload: dict[str, Any] | None = None,
        waiting_room_level_adhoc: str | None = None,
        waiting_room_level_calendar: str | None = None,
        cloud_recording_email_receivers: list[str] | None = None,
        summarization_email_receivers: list[str] | None = None,
        cloud_recording_allowed_roles: list[str] | None = None,
        summarization_allowed_roles: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = dict(file_payload or {})
        overrides = {
            "waiting_room_level_adhoc": waiting_room_level_adhoc,
            "waiting_room_level_calendar": waiting_room_level_calendar,
            "cloud_recording_email_receivers": cloud_recording_email_receivers,
            "summarization_email_receivers": summarization_email_receivers,
            "cloud_recording_allowed_roles": cloud_recording_allowed_roles,
            "summarization_allowed_roles": summarization_allowed_roles,
        }
        for field, value in overrides.items():
            if value is None:
                continue
            payload[field] = {"value": value}
        normalized = self._normalize_org_settings_payload(payload)
        if not normalized:
            raise ValueError("Organization settings update requires a full payload or explicit fields")
        return normalized

    def create_conference(
        self,
        *,
        access_level: str = "PUBLIC",
        waiting_room_level: str = "PUBLIC",
        cohosts: list[str] | None = None,
        live_stream: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_cohosts = self._normalize_cohosts(cohosts or []) or []
        payload = self._conference_payload(
            access_level=access_level,
            waiting_room_level=waiting_room_level,
            live_stream=live_stream,
            cohosts=normalized_cohosts,
            include_cohosts=True,
        )
        with self._telemost_errors():
            created = self._api_create_conference(payload) or {}
        return self._normalize_write_conference(
            created,
            payload=payload,
            cohosts=normalized_cohosts,
        )

    def get_cohosts(self, conference_id: str) -> list[str]:
        with self._telemost_errors():
            response = self._api_get_cohosts(conference_id) or {}
        cohosts = response.get("cohosts", [])
        return [entry.get("email") for entry in cohosts if isinstance(entry, dict) and entry.get("email")]

    def get_conference(self, conference_id: str) -> dict[str, Any]:
        with self._telemost_errors():
            conference = self._api_get_conference(conference_id) or {}
        cohosts = self.get_cohosts(conference_id)
        return self._normalize_conference(conference, cohosts=cohosts)

    def update_conference(
        self,
        conference_id: str,
        *,
        access_level: str | None = None,
        waiting_room_level: str | None = None,
        cohosts: list[str] | object = _UNSET,
        live_stream: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self._conference_payload(
            access_level=access_level,
            waiting_room_level=waiting_room_level,
            live_stream=live_stream,
            cohosts=_UNSET,
            include_cohosts=False,
        )
        last_response: dict[str, Any] | None = None
        if payload:
            with self._telemost_errors():
                last_response = self._api_patch_conference(conference_id, payload) or {}
        normalized_cohosts: list[str] | None = None
        if cohosts is not _UNSET and cohosts is not None:
            normalized_cohosts = self._normalize_cohosts(cohosts)
            with self._telemost_errors():
                self._api_put_cohosts(
                    conference_id,
                    {"cohosts": [{"email": email} for email in normalized_cohosts or []]},
                )
        response = last_response or {"id": conference_id}
        return self._normalize_write_conference(
            response,
            payload=payload,
            cohosts=normalized_cohosts,
            conference_id=conference_id,
        )

    def get_org_settings(self, *, org_id: int | str | None = None) -> dict[str, Any]:
        resolved_org_id = self._resolve_org_id(org_id)
        with self._telemost_errors():
            settings = self._api_get_org_settings(resolved_org_id) or {}
        settings["org_id"] = resolved_org_id
        return settings

    def update_org_settings(
        self,
        settings: dict[str, Any],
        *,
        org_id: int | str | None = None,
    ) -> dict[str, Any]:
        resolved_org_id = self._resolve_org_id(org_id)
        payload = self._normalize_org_settings_payload(settings)
        if not payload:
            raise ValueError("Organization settings payload cannot be empty")
        with self._telemost_errors():
            updated = self._api_put_org_settings(resolved_org_id, payload) or {}
        updated["org_id"] = resolved_org_id
        return updated
