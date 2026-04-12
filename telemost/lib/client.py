"""Yandex Telemost API client."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import requests

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.auth import resolve_token
from common.config import load_runtime_context

DEFAULT_API_BASE = "https://cloud-api.yandex.net/v1/telemost-api"
READ_SCOPES = ["telemost-api:conferences.read"]
CREATE_SCOPES = ["telemost-api:conferences.create"]
UPDATE_SCOPES = ["telemost-api:conferences.update"]
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
        self.session = session or requests.Session()

    def _auth_headers(self, scopes: list[str]) -> dict[str, str]:
        token_info = resolve_token(
            account=self.account,
            skill="telemost",
            data_dir=self.data_dir,
            config=self.config,
            required_scopes=scopes,
        )
        return {"Authorization": f"OAuth {token_info.token}"}

    def _request(
        self,
        method: str,
        path: str,
        *,
        scopes: list[str],
        expected_statuses: tuple[int, ...],
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        url = f"{self.api_base}{path}"
        headers = self._auth_headers(scopes)
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                json=json_body,
                params=params,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise TelemostError(
                "Telemost request failed",
                method=method,
                path=path,
                reason=str(exc),
            ) from exc

        if response.status_code not in expected_statuses:
            details = {
                "method": method,
                "path": path,
                "status_code": response.status_code,
            }
            try:
                details["response"] = response.json()
            except ValueError:
                details["response"] = response.text[:500]

            if response.status_code in (401, 403):
                raise TelemostError("Telemost API access denied", **details)
            if response.status_code == 402:
                raise TelemostError(
                    "Telemost live stream requires a paid Yandex 360 tariff",
                    **details,
                )
            if response.status_code == 404:
                raise TelemostError("Telemost conference not found", **details)
            raise TelemostError("Telemost API request failed", **details)

        if response.status_code == 204:
            return None
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise TelemostError(
                "Telemost API returned invalid JSON",
                method=method,
                path=path,
                status_code=response.status_code,
                response=response.text[:500],
            ) from exc

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
        }
        for field in (
            "access_level",
            "waiting_room_level",
            "sip_uri_meeting",
            "sip_uri_telemost",
            "sip_id",
        ):
            if conference.get(field) is not None:
                normalized[field] = conference.get(field)
        if conference.get("live_stream") is not None:
            normalized["live_stream"] = conference.get("live_stream")
        if cohosts is not None:
            normalized["cohosts"] = cohosts
        return normalized

    def _cohosts_path(self, conference_id: str) -> str:
        return f"/conferences/{conference_id}/cohosts"

    def _resolve_org_id(self, org_id: int | str | None, *, scopes: list[str]) -> int:
        if org_id is not None:
            return int(org_id)
        token_info = resolve_token(
            account=self.account,
            skill="telemost",
            data_dir=self.data_dir,
            config=self.config,
            required_scopes=scopes,
        )
        token_org_id = token_info.token_data.get("org_id")
        if token_org_id is None:
            raise TelemostError(
                "Organization ID is required; provide --org-id or save org_id in the token file",
                account=self.account,
                token_path=str(token_info.token_path),
            )
        return int(token_org_id)

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
        payload = self._conference_payload(
            access_level=access_level,
            waiting_room_level=waiting_room_level,
            live_stream=live_stream,
            cohosts=cohosts or [],
            include_cohosts=True,
        )
        created = self._request(
            "POST",
            "/conferences",
            scopes=CREATE_SCOPES,
            expected_statuses=(201,),
            json_body=payload,
        ) or {}
        conference_id = created.get("id")
        if not conference_id:
            return self._normalize_conference(created, cohosts=cohosts or [])
        return self._normalize_conference(created, cohosts=cohosts or [])

    def get_cohosts(self, conference_id: str) -> list[str]:
        response = self._request(
            "GET",
            self._cohosts_path(conference_id),
            scopes=READ_SCOPES,
            expected_statuses=(200,),
        ) or {}
        cohosts = response.get("cohosts", [])
        return [entry.get("email") for entry in cohosts if isinstance(entry, dict) and entry.get("email")]

    def get_conference(self, conference_id: str) -> dict[str, Any]:
        conference = self._request(
            "GET",
            f"/conferences/{conference_id}",
            scopes=READ_SCOPES,
            expected_statuses=(200,),
        ) or {}
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
            last_response = self._request(
                "PATCH",
                f"/conferences/{conference_id}",
                scopes=UPDATE_SCOPES,
                expected_statuses=(200,),
                json_body=payload,
            ) or {}
        normalized_cohosts: list[str] | None = None
        if cohosts is not _UNSET and cohosts is not None:
            normalized_cohosts = self._normalize_cohosts(cohosts)
            self._request(
                "PUT",
                self._cohosts_path(conference_id),
                scopes=UPDATE_SCOPES,
                expected_statuses=(204,),
                json_body={"cohosts": [{"email": email} for email in normalized_cohosts or []]},
            )
        if last_response:
            return self._normalize_conference(last_response, cohosts=normalized_cohosts)
        return {"id": conference_id, "cohosts": normalized_cohosts or []}

    def get_org_settings(self, *, org_id: int | str | None = None) -> dict[str, Any]:
        resolved_org_id = self._resolve_org_id(org_id, scopes=READ_SCOPES)
        settings = self._request(
            "GET",
            f"/organizations/{resolved_org_id}/settings",
            scopes=READ_SCOPES,
            expected_statuses=(200,),
        ) or {}
        settings["org_id"] = resolved_org_id
        return settings

    def update_org_settings(
        self,
        settings: dict[str, Any],
        *,
        org_id: int | str | None = None,
    ) -> dict[str, Any]:
        resolved_org_id = self._resolve_org_id(org_id, scopes=UPDATE_SCOPES)
        payload = self._normalize_org_settings_payload(settings)
        if not payload:
            raise ValueError("Organization settings payload cannot be empty")
        updated = self._request(
            "PUT",
            f"/organizations/{resolved_org_id}/settings",
            scopes=UPDATE_SCOPES,
            expected_statuses=(200,),
            json_body=payload,
        ) or {}
        updated["org_id"] = resolved_org_id
        return updated
