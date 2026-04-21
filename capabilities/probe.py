#!/usr/bin/env python3
"""Run capability probes from capabilities/methods.json and regenerate outputs."""

from __future__ import annotations

import argparse
import imaplib
import json
import re
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "capabilities"
RAW = CAP / "raw"
MATRIX = CAP / "matrix.json"
METHOD_SCOPE_MAP = CAP / "method-scope-map.json"
STATUSES = ["works", "does_not_work", "not_applicable", "not_tested", "unclear_needs_retest"]
SMTP_NETWORK_UNREACHABLE: set[tuple[str, int]] = set()
YANDEX_DIAGNOSTIC_RE = re.compile(r"\bsc=[A-Za-z0-9_-]+")


class ProbeResponse:
    def __init__(self, status_code: int, ok: bool, payload: dict[str, Any] | None = None, text: str = "") -> None:
        self.status_code = status_code
        self.ok = ok
        self._payload = payload or {}
        self.text = text
        self.headers: dict[str, str] = {}

    def json(self) -> dict[str, Any]:
        return self._payload


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def redact_text(value: Any, limit: int = 160) -> str:
    return YANDEX_DIAGNOSTIC_RE.sub("sc=<redacted>", str(value))[:limit]


def load_capabilities() -> dict[str, Any]:
    return load_json(CAP / "methods.json")


def local_probe_variables(service: str) -> dict[str, Any]:
    path = CAP / "probe.local.json"
    if not path.exists():
        return {}
    data = load_json(path)
    merged: dict[str, Any] = {}
    for key in ("variables", service):
        value = data.get(key, {})
        if isinstance(value, dict):
            merged.update(value)
    return merged


def method_inventory(service: str, methods: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {method["id"]: method for method in methods if method.get("sub_skill") == service}


def service_scopes(service: str, capabilities: dict[str, Any]) -> list[str]:
    client_ids = load_json(CAP / "atomic.client_id.json")
    plan = capabilities["probe_plans"][service]
    if plan.get("auth_contexts"):
        return [scope for scope in client_ids if scope in plan["auth_contexts"]]
    prefix = f"scope:"
    encoded = json.dumps(
        {
            "plan": plan,
            "methods": [method for method in capabilities["methods"] if method.get("sub_skill") == service],
        },
        ensure_ascii=False,
    )
    referenced = {
        value.removeprefix(prefix)
        for value in re.findall(r'"auth":\s*"([^"]+)"', encoded)
        if value.startswith(prefix)
    }
    return [scope for scope in client_ids if scope in referenced]


def expand_scope_set(scope_id: str) -> list[str] | None:
    match = re.fullmatch(r"(.+)\.\{([^{}]+)\}", scope_id)
    if not match:
        return None
    prefix, names = match.groups()
    return [f"{prefix}.{name.strip()}" for name in names.split(",") if name.strip()]


def atomic_context(scope_id: str) -> bool:
    return expand_scope_set(scope_id) is None


def relevant_combined_contexts(method_rows: list[dict[str, Any]], combined_contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failed_atomic = {
        row["scope_id"]
        for row in method_rows
        if row["scope_id"] != "public" and atomic_context(row["scope_id"]) and row["status"] != "works"
    }
    return [
        context
        for context in combined_contexts
        if set(expand_scope_set(context["scope_id"]) or []).issubset(failed_atomic)
    ]


def render(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return value.format(**variables)
    if isinstance(value, list):
        return [render(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: render(item, variables) for key, item in value.items()}
    return value


def url_for(config: dict[str, Any], service: str, methods: dict[str, dict[str, Any]], method_id: str, variables: dict[str, Any]) -> str:
    path = render(methods[method_id]["path"], variables)
    if str(path).startswith("http://") or str(path).startswith("https://"):
        return str(path)
    return config["urls"][f"{service}_api"] + path


def token_for(auth: str | None, context: dict[str, Any], tokens: dict[str, str], methods: dict[str, dict[str, Any]], method_id: str) -> str | None:
    if auth in (None, "public"):
        return None
    if auth == "context":
        return context["token"]
    if auth.startswith("scope:"):
        token = tokens.get(auth.removeprefix("scope:"))
        if token:
            return token
    raise RuntimeError(f"Cannot resolve auth {auth!r} for {method_id}")


def request(method: str, url: str, token: str | None, **kwargs: Any) -> requests.Response | ProbeResponse:
    headers = {} if token is None else {"Authorization": f"OAuth {token}"}
    headers.update(kwargs.pop("headers", {}) or {})
    try:
        return requests.request(method, url, headers=headers, timeout=30, **kwargs)
    except requests.RequestException as exc:
        return ProbeResponse(0, False, {"error": exc.__class__.__name__, "description": redact_text(exc)})


def http_summary(resp: requests.Response) -> dict[str, Any]:
    out: dict[str, Any] = {
        "status_code": resp.status_code,
        "ok": resp.ok,
        "content_type": resp.headers.get("content-type", "").split(";")[0],
    }
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        out["json_keys"] = sorted(map(str, payload.keys()))[:20]
        if payload.get("code"):
            out["code"] = str(payload["code"])
        if payload.get("message"):
            out["message"] = redact_text(payload["message"])
        if payload.get("error"):
            out["error"] = str(payload["error"])
        if payload.get("description"):
            out["description"] = redact_text(payload["description"])
    return out


def response_text(resp: requests.Response | ProbeResponse) -> str:
    return getattr(resp, "text", "") or ""


def auth_accepted(resp: requests.Response, request_spec: dict[str, Any]) -> bool:
    summary = http_summary(resp)
    request_headers = getattr(getattr(resp, "request", None), "headers", {}) or {}
    if request_headers.get("Authorization") and resp.status_code in request_spec.get("auth_success_status", []):
        return True
    return bool(summary.get("error") in request_spec.get("auth_success_errors", []))


def result_status(resp: requests.Response | ProbeResponse, request_spec: dict[str, Any]) -> str:
    summary = http_summary(resp)
    if resp.ok or auth_accepted(resp, request_spec):
        return "works"
    if summary.get("error") in request_spec.get("inconclusive_errors", []):
        return "unclear_needs_retest"
    return "does_not_work"


def row(method_id: str, scope_id: str, resp: requests.Response, fixture_id: str, request_spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": now(),
        "method_id": method_id,
        "scope_id": scope_id,
        "status": result_status(resp, request_spec),
        "http": http_summary(resp),
        "request_fixture_id": fixture_id,
    }


def debug_probe(method_id: str, scope_id: str, resp: requests.Response, request_spec: dict[str, Any]) -> None:
    summary = http_summary(resp)
    parts = [
        "probe",
        f"method={method_id}",
        f"context={scope_id}",
        f"status={summary['status_code']}",
        f"result={result_status(resp, request_spec)}",
    ]
    if summary.get("error"):
        parts.append(f"error={summary['error']}")
    print(" ".join(parts), file=sys.stderr, flush=True)


def extract_value(payload: Any, spec: Any) -> Any:
    if isinstance(spec, str):
        value = payload
        for part in spec.split("."):
            if isinstance(value, list) and part.isdigit():
                value = value[int(part)] if int(part) < len(value) else None
                continue
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value
    for candidate in spec.get("paths", []):
        value = extract_value(payload, candidate)
        if value:
            return value
    if "path" not in spec:
        return None
    value = extract_value(payload, spec["path"])
    pattern = spec.get("regex")
    if pattern and isinstance(value, str):
        match = re.search(pattern, value)
        return match.group(1) if match else None
    return value


def extract_from_response(resp: requests.Response | ProbeResponse, spec: Any) -> Any:
    if isinstance(spec, dict) and "regex" in spec:
        match = re.search(spec["regex"], response_text(resp), re.S)
        return match.group(1) if match else None
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    return extract_value(payload, spec)


def store_extracts(resp: requests.Response | ProbeResponse, extracts: dict[str, Any], variables: dict[str, Any]) -> None:
    if not extracts:
        return
    for name, spec in extracts.items():
        value = extract_from_response(resp, spec)
        if value:
            variables[name] = value


def accepted(resp: requests.Response, action: dict[str, Any]) -> bool:
    statuses = action.get("accept_status")
    return resp.status_code in statuses if statuses else resp.ok


def oauth_info(token: str) -> dict[str, Any]:
    resp = requests.get("https://login.yandex.ru/info", headers={"Authorization": f"OAuth {token}"}, timeout=30)
    if not resp.ok:
        return {}
    payload = resp.json()
    login = payload.get("default_email") or payload.get("login")
    return {"account_email": login, "account_login": login, "account_id": payload.get("id")}


def imap_response(action: dict[str, Any], context: dict[str, Any], config: dict[str, Any], variables: dict[str, Any]) -> ProbeResponse:
    server = config["imap"]["server"]
    port = int(config["imap"]["port"])
    email = variables.get("account_email")
    token = context.get("token")
    if not email or not token:
        return ProbeResponse(0, False, {"error": "MissingImapAuthContext"})
    conn: imaplib.IMAP4_SSL | None = None
    try:
        conn = imaplib.IMAP4_SSL(server, port)
        auth = f"user={email}\1auth=Bearer {token}\1\1"
        conn.authenticate("XOAUTH2", lambda _: auth)
        command = action.get("imap_command", "authenticate")
        mailbox = action.get("mailbox", "INBOX")
        target_mailbox = action.get("target_mailbox")
        probe_message = render(action.get("message", "Subject: OpenClaw GH38 IMAP probe\r\n\r\nprobe\r\n"), variables).encode()
        force_readonly = context.get("scope_id") == "mail:imap_ro"

        def readonly(default: bool = True) -> bool:
            return True if force_readonly else bool(action.get("readonly", default))

        def imap_result(status: str, data: Any = None, *, ok_status: str = "OK") -> ProbeResponse:
            return ProbeResponse(
                200 if status == ok_status else 500,
                status == ok_status,
                {"imap_status": status, "data": str(data)[:160]},
            )

        def selected_message_id(open_readonly: bool = False) -> bytes | None:
            status, _ = conn.select(mailbox, readonly=True if force_readonly else open_readonly)
            if status != "OK":
                return None
            status, data = conn.search(None, "ALL")
            ids = data[0].split() if status == "OK" and data else []
            return ids[-1] if ids else None

        if command == "authenticate":
            return ProbeResponse(200, True, {"imap_status": "OK"})
        if command == "capability":
            status, data = conn.capability()
            return imap_result(status, data)
        if command == "noop":
            status, data = conn.noop()
            return imap_result(status, data)
        if command == "logout":
            status, data = conn.logout()
            conn = None
            return imap_result(status, data, ok_status="BYE")
        if command == "list":
            status, data = conn.list()
            return imap_result(status, data)
        if command == "lsub":
            status, data = conn.lsub()
            return imap_result(status, data)
        if command == "status":
            status, data = conn.status(mailbox, action.get("status_items", "(MESSAGES UIDNEXT UIDVALIDITY)"))
            return imap_result(status, data)
        if command == "create":
            status, data = conn.create(mailbox)
            return imap_result(status, data)
        if command == "delete":
            status, data = conn.delete(mailbox)
            return imap_result(status, data)
        if command == "rename":
            if not target_mailbox:
                return ProbeResponse(0, False, {"error": "MissingTargetMailbox"})
            status, data = conn.rename(mailbox, target_mailbox)
            return imap_result(status, data)
        if command == "subscribe":
            status, data = conn.subscribe(mailbox)
            return imap_result(status, data)
        if command == "unsubscribe":
            status, data = conn.unsubscribe(mailbox)
            return imap_result(status, data)
        if command == "append":
            status, data = conn.append(mailbox, action.get("flags"), None, probe_message)
            return imap_result(status, data)
        if command == "select":
            status, data = conn.select(mailbox, readonly=readonly(True))
            return ProbeResponse(200 if status == "OK" else 500, status == "OK", {"imap_status": status, "count": data[0].decode(errors="replace") if data else None})
        if command == "examine":
            status, data = conn.select(mailbox, readonly=True)
            return ProbeResponse(200 if status == "OK" else 500, status == "OK", {"imap_status": status, "count": data[0].decode(errors="replace") if data else None})
        status, data = conn.select(mailbox, readonly=readonly(True))
        if status != "OK":
            return ProbeResponse(500, False, {"error": "ImapSelectFailed", "imap_status": status})
        if command == "check":
            status, data = conn.check()
            return imap_result(status, data)
        if command == "close":
            status, data = conn.close()
            return imap_result(status, data)
        if command == "expunge":
            status, data = conn.expunge()
            return imap_result(status, data)
        if command == "search":
            status, data = conn.search(None, *(action.get("criteria") or ["ALL"]))
            return ProbeResponse(200 if status == "OK" else 500, status == "OK", {"imap_status": status, "matched": bool(data and data[0])})
        if command == "fetch":
            msg_id = selected_message_id(open_readonly=readonly(True))
            if not msg_id:
                return ProbeResponse(404, False, {"error": "NoMessagesToFetch", "imap_status": status})
            status, fetched = conn.fetch(msg_id, action.get("fetch_parts", "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"))
            return ProbeResponse(200 if status == "OK" else 500, status == "OK", {"imap_status": status, "fetched": bool(fetched)})
        if command == "store":
            msg_id = selected_message_id(open_readonly=readonly(False))
            if not msg_id:
                return ProbeResponse(404, False, {"error": "NoMessagesToStore", "imap_status": status})
            status, data = conn.store(msg_id, action.get("store_command", "+FLAGS"), action.get("flags", "\\Seen"))
            return imap_result(status, data)
        if command == "copy":
            msg_id = selected_message_id(open_readonly=readonly(True))
            if not msg_id or not target_mailbox:
                return ProbeResponse(404, False, {"error": "NoMessageOrTargetForCopy", "imap_status": status})
            status, data = conn.copy(msg_id, target_mailbox)
            return imap_result(status, data)
        if command == "uid_search":
            status, data = conn.uid("SEARCH", None, *(action.get("criteria") or ["ALL"]))
            return ProbeResponse(200 if status == "OK" else 500, status == "OK", {"imap_status": status, "matched": bool(data and data[0])})
        if command == "uid_fetch":
            status, data = conn.uid("SEARCH", None, "ALL")
            ids = data[0].split() if status == "OK" and data else []
            if not ids:
                return ProbeResponse(404, False, {"error": "NoMessagesToUidFetch", "imap_status": status})
            status, fetched = conn.uid("FETCH", ids[-1], action.get("fetch_parts", "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"))
            return ProbeResponse(200 if status == "OK" else 500, status == "OK", {"imap_status": status, "fetched": bool(fetched)})
        if command == "uid_store":
            status, data = conn.uid("SEARCH", None, "ALL")
            ids = data[0].split() if status == "OK" and data else []
            if not ids:
                return ProbeResponse(404, False, {"error": "NoMessagesToUidStore", "imap_status": status})
            status, data = conn.uid("STORE", ids[-1], action.get("store_command", "+FLAGS"), action.get("flags", "\\Seen"))
            return imap_result(status, data)
        if command == "uid_copy":
            status, data = conn.uid("SEARCH", None, "ALL")
            ids = data[0].split() if status == "OK" and data else []
            if not ids or not target_mailbox:
                return ProbeResponse(404, False, {"error": "NoMessageOrTargetForUidCopy", "imap_status": status})
            status, data = conn.uid("COPY", ids[-1], target_mailbox)
            return imap_result(status, data)
        if command == "uid_delete_matching":
            criteria = action.get("criteria") or ["ALL"]
            status, data = conn.uid("SEARCH", None, *criteria)
            ids = data[0].split() if status == "OK" and data else []
            if not ids:
                return ProbeResponse(404, False, {"error": "NoMatchingMessage", "imap_status": status})
            target_uid = ids[-1]
            try:
                store_status, store_data = conn.uid("STORE", target_uid, "+FLAGS.SILENT", "(\\Deleted)")
            except Exception as exc:
                return ProbeResponse(
                    535,
                    False,
                    {
                        "error": "ImapStoreDeletedFailed",
                        "description": str(exc)[:160],
                        "target_uid": target_uid.decode(errors="replace"),
                        "matches_before": len(ids),
                    },
                )
            expunge_status, expunge_data = conn.expunge()
            verify_status, verify_data = conn.uid("SEARCH", None, "UID", target_uid.decode())
            remaining = verify_data[0].split() if verify_status == "OK" and verify_data and verify_data[0] else []
            sender_status, sender_data = conn.uid("SEARCH", None, *criteria)
            sender_remaining = sender_data[0].split() if sender_status == "OK" and sender_data and sender_data[0] else []
            return ProbeResponse(
                200 if store_status == "OK" and expunge_status == "OK" and not remaining else 500,
                store_status == "OK" and expunge_status == "OK" and not remaining,
                {
                    "imap_status": store_status,
                    "expunge_status": expunge_status,
                    "target_uid": target_uid.decode(errors="replace"),
                    "target_uid_remaining": len(remaining),
                    "matches_before": len(ids),
                    "matches_after": len(sender_remaining),
                },
            )
        return ProbeResponse(0, False, {"error": "UnknownImapCommand"})
    except Exception as exc:
        return ProbeResponse(535, False, {"error": exc.__class__.__name__, "description": str(exc)[:160]})
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass


def smtp_response(action: dict[str, Any], context: dict[str, Any], config: dict[str, Any], variables: dict[str, Any]) -> ProbeResponse:
    server = config["smtp"]["server"]
    port = int(config["smtp"]["port"])
    email = variables.get("account_email")
    token = context.get("token")
    to_addr = action.get("to")
    allowed = set(action.get("allowed_recipients", []))
    if action.get("smtp_command") == "send" and to_addr not in allowed:
        return ProbeResponse(0, False, {"error": "RecipientNotAllowed"})
    if not email or not token:
        return ProbeResponse(0, False, {"error": "MissingSmtpAuthContext"})
    if (server, port) in SMTP_NETWORK_UNREACHABLE:
        return ProbeResponse(0, False, {"error": "NetworkUnreachable", "description": "cached"})
    try:
        auth = f"user={email}\1auth=Bearer {token}\1\1"
        with smtplib.SMTP_SSL(server, port, timeout=float(action.get("timeout_seconds", 30))) as conn:
            conn.ehlo()
            code, message = conn.docmd("AUTH", "XOAUTH2 " + __import__("base64").b64encode(auth.encode()).decode())
            if code != 235:
                return ProbeResponse(code, False, {"error": "SmtpAuthFailed", "description": message.decode(errors="replace")[:160]})
            command = action.get("smtp_command")
            if command == "authenticate":
                return ProbeResponse(code, True, {"smtp_status": str(code)})
            if command == "noop":
                code, message = conn.noop()
                return ProbeResponse(code, 200 <= code < 400, {"smtp_status": str(code), "description": message.decode(errors="replace")[:160]})
            if command == "rset":
                code, message = conn.rset()
                return ProbeResponse(code, 200 <= code < 400, {"smtp_status": str(code), "description": message.decode(errors="replace")[:160]})
            if command == "quit":
                code, message = conn.quit()
                return ProbeResponse(code, 200 <= code < 400, {"smtp_status": str(code), "description": message.decode(errors="replace")[:160]})
            msg = EmailMessage()
            msg["From"] = email
            msg["To"] = to_addr
            msg["Subject"] = render(action.get("subject", "OpenClaw capability probe"), variables)
            msg.set_content(render(action.get("body", "OpenClaw capability probe"), variables))
            conn.send_message(msg)
            return ProbeResponse(250, True, {"smtp_status": "sent"})
    except OSError as exc:
        SMTP_NETWORK_UNREACHABLE.add((server, port))
        return ProbeResponse(0, False, {"error": "NetworkUnreachable", "description": str(exc)[:160]})
    except Exception as exc:
        return ProbeResponse(535, False, {"error": exc.__class__.__name__, "description": str(exc)[:160]})


def choose_variant(method: dict[str, Any], scope_id: str) -> dict[str, Any]:
    variants = method.get("probe_requests", [])
    if not variants:
        raise RuntimeError(f"{method['id']} missing probe_requests")
    fallback = variants[0]
    for variant in variants:
        scopes = variant.get("scopes")
        if scopes and scope_id in scopes:
            return variant
        if variant.get("default"):
            fallback = variant
    return fallback


def run_action(
    service: str,
    action: dict[str, Any],
    context: dict[str, Any],
    variables: dict[str, Any],
    config: dict[str, Any],
    methods: dict[str, dict[str, Any]],
    tokens: dict[str, str],
) -> requests.Response | None:
    action_type = action.get("type", "request")
    if action_type == "sleep":
        time.sleep(float(action["seconds"]))
        return None
    if action_type == "upload":
        url = render(action["url"], variables)
        data = render(action.get("data", ""), variables).encode()
        resp = requests.put(url, data=data, timeout=30)
        if not accepted(resp, action):
            raise RuntimeError(f"{action['id']} failed: HTTP {resp.status_code}")
        return resp
    if action_type != "request":
        if action_type == "imap":
            return imap_response(render(action, variables), context, config, variables)
        if action_type == "smtp":
            return smtp_response(render(action, variables), context, config, variables)
        raise RuntimeError(f"Unknown action type {action_type}")

    method_id = action["method_id"]
    token = token_for(action.get("auth"), context, tokens, methods, method_id)
    kwargs: dict[str, Any] = {}
    for key in ("params", "json", "headers"):
        if key in action:
            kwargs[key] = render(action[key], variables)
    if "data" in action:
        kwargs["data"] = render(action["data"], variables).encode()
    url = render(action["url"], variables) if action.get("url") else url_for(config, service, methods, method_id, variables)
    resp = request(
        methods[method_id]["http_method"],
        url,
        token,
        **kwargs,
    )
    store_extracts(resp, action.get("extract", {}), variables)
    if not accepted(resp, action) and not action.get("allow_failure"):
        raise RuntimeError(f"{action['id']} failed: HTTP {resp.status_code}")
    return resp


def run_actions(
    service: str,
    actions: list[dict[str, Any]],
    context: dict[str, Any],
    variables: dict[str, Any],
    config: dict[str, Any],
    methods: dict[str, dict[str, Any]],
    tokens: dict[str, str],
) -> None:
    for action in actions:
        attempts = int(action.get("attempts", 1))
        wait_seconds = float(action.get("wait_seconds", 0))
        until_var = action.get("until_var")
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                run_action(service, action, context, variables, config, methods, tokens)
                if not until_var or variables.get(until_var):
                    break
            except Exception as exc:
                last_error = exc
                if attempt == attempts - 1:
                    raise
            if wait_seconds:
                time.sleep(wait_seconds)
        else:
            if last_error:
                raise last_error
            raise RuntimeError(f"{action['id']} did not produce {until_var}")


def probe_service(service: str, only_method: str | None = None, only_scope: str | None = None) -> None:
    capabilities = load_capabilities()
    plan = capabilities["probe_plans"][service]
    methods = method_inventory(service, capabilities["methods"])
    config = load_json(ROOT / "config.skill.json")
    token_data = load_json(CAP / "atomic.token")
    scopes = service_scopes(service, capabilities)
    tokens = {scope: str(token_data.get(scope, "")).strip() for scope in scopes}
    missing = [scope for scope, token in tokens.items() if not token]
    if missing:
        raise SystemExit(f"Missing {service} tokens: {', '.join(missing)}")

    run_id = str(int(time.time()))
    base_vars = render(plan.get("variables", {}), {"run_id": run_id})
    base_vars.update(render(local_probe_variables(service), {"run_id": run_id}))
    base_vars["run_id"] = run_id
    base_vars.update(config.get("urls", {}))
    for key in ("imap", "smtp"):
        for item_key, value in config.get(key, {}).items():
            base_vars[f"{key}_{item_key}"] = value
    if plan.get("with_oauth_info") and len(scopes) == 1:
        base_vars.update(oauth_info(tokens[scopes[0]]))
    fixture_context = {"scope_id": "fixture", "token": None, "context_key": "fixture"}
    rows: list[dict[str, Any]] = []
    public_methods: set[str] = set()

    run_actions(service, plan.get("setup", []), fixture_context, base_vars, config, methods, tokens)

    public_context = {"scope_id": "public", "token": None, "context_key": "public"}
    token_contexts = [
        {"scope_id": scope, "token": token, "context_key": re.sub(r"[^A-Za-z0-9]+", "_", scope).strip("_")}
        for scope, token in tokens.items()
    ]
    if plan.get("with_oauth_info"):
        for context in token_contexts:
            context.update(oauth_info(context["token"]))
    atomic_contexts = [context for context in token_contexts if atomic_context(context["scope_id"])]
    combined_contexts = [context for context in token_contexts if not atomic_context(context["scope_id"])]
    contexts = [public_context] + atomic_contexts + combined_contexts
    if only_scope:
        contexts = [context for context in contexts if context["scope_id"] == only_scope]
        if not contexts:
            raise RuntimeError(f"scope {only_scope} is not available for {service}")
    method_ids = [method_id for method_id in methods if method_id in plan.get("methods", [])]
    if only_method:
        if only_method not in method_ids:
            raise RuntimeError(f"method {only_method} is not in {service} probe plan")
        method_ids = [only_method]
    missing_methods = sorted(set(methods) - set(method_ids))
    if missing_methods and not only_method:
        raise RuntimeError("probe plan missing methods: " + ", ".join(missing_methods))

    try:
        for method_id in method_ids:
            method_rows: list[dict[str, Any]] = []
            method = methods[method_id]
            if only_scope:
                method_contexts = contexts
            else:
                method_contexts = [public_context]
                method_contexts.extend(atomic_contexts)
            for context in method_contexts:
                if context["scope_id"] != "public" and method_id in public_methods:
                    continue
                variables = {**base_vars, **context}
                variant = choose_variant(method, context["scope_id"])
                if context["scope_id"] != "public" and variant.get("scopes") and context["scope_id"] not in variant["scopes"]:
                    continue
                run_actions(service, variant.get("before", []), context, variables, config, methods, tokens)
                action = {"id": variant["id"], "method_id": method_id, "auth": "context", "allow_failure": True, **variant["request"]}
                resp = run_action(service, action, context, variables, config, methods, tokens)
                if resp is None:
                    raise RuntimeError(f"{method_id} did not produce an HTTP response")
                debug_probe(method_id, context["scope_id"], resp, variant["request"])
                result = row(method_id, context["scope_id"], resp, variant["id"], variant["request"])
                rows.append(result)
                method_rows.append(result)
                if context["scope_id"] == "public" and resp.ok:
                    public_methods.add(method_id)
                run_actions(service, variant.get("after", []), context, variables, config, methods, tokens)
            if only_scope or method_id in public_methods or any(row["status"] == "works" for row in method_rows):
                continue
            for context in relevant_combined_contexts(method_rows, combined_contexts):
                variables = {**base_vars, **context}
                variant = choose_variant(method, context["scope_id"])
                if context["scope_id"] != "public" and variant.get("scopes") and context["scope_id"] not in variant["scopes"]:
                    continue
                run_actions(service, variant.get("before", []), context, variables, config, methods, tokens)
                action = {"id": variant["id"], "method_id": method_id, "auth": "context", "allow_failure": True, **variant["request"]}
                resp = run_action(service, action, context, variables, config, methods, tokens)
                if resp is None:
                    raise RuntimeError(f"{method_id} did not produce an HTTP response")
                debug_probe(method_id, context["scope_id"], resp, variant["request"])
                rows.append(row(method_id, context["scope_id"], resp, variant["id"], variant["request"]))
                run_actions(service, variant.get("after", []), context, variables, config, methods, tokens)
    finally:
        cleanup_errors: list[str] = []
        for action in plan.get("cleanup", []):
            try:
                run_action(service, action, fixture_context, base_vars, config, methods, tokens)
            except Exception as exc:
                cleanup_errors.append(str(exc))

    output = {
        "probe": service,
        "timestamp": now(),
        "fixture": {"id": plan.get("fixture_id", service), "variables": "<redacted>"},
        "rows": rows,
        "cleanup_errors": cleanup_errors,
    }
    RAW.mkdir(parents=True, exist_ok=True)
    raw_name = f"{service}-probe.json"
    if only_method:
        raw_name = f"{service}-{only_method.replace('.', '_')}-probe.json"
    write_json(RAW / raw_name, output)
    print(f"{service} rows={len(rows)}")


def build_matrix() -> None:
    cells: list[dict[str, Any]] = []
    for path in sorted(RAW.glob("*-probe.json")):
        probe = load_json(path)
        for r in probe.get("rows", []):
            scope_id = r["scope_id"]
            cell = {
                "method_id": r["method_id"],
                "scope_id": scope_id,
                "status": r["status"],
                "timestamp": r["timestamp"],
                "token_fixture_id": "no_oauth" if scope_id == "public" else f"atomic:{scope_id}",
                "request_fixture_id": r.get("request_fixture_id", probe.get("probe", path.stem)),
                "http_status": r.get("http", {}).get("status_code"),
                "protocol_result": "http",
                "evidence": str(path.relative_to(ROOT)),
            }
            if r.get("http", {}).get("error"):
                cell["error"] = r["http"]["error"]
            cells.append(cell)
    payload = {
        "schema_version": 1,
        "generated_by": "capabilities/probe.py",
        "generated_from": sorted(str(path.relative_to(ROOT)) for path in RAW.glob("*-probe.json")),
        "generated_for": "GH38-api-method-scope-capability-matrix",
        "status_values": STATUSES,
        "default_cell_status": "not_tested",
        "semantics": "public is tested first; if public works, OAuth scope cells for that method are omitted.",
        "method_inventory": "capabilities/methods.json",
        "scope_inventory": "references/yandex-oauth-scopes.json",
        "atomic_client_id_inventory": "capabilities/atomic.client_id.json",
        "cells": cells,
    }
    write_json(MATRIX, payload)
    print(f"matrix cells={len(cells)}")


def build_method_scope_map() -> None:
    matrix = load_json(MATRIX)
    method_scope_map: dict[str, Any] = {"schema_version": 1, "generated_by": "capabilities/probe.py", "methods": {}}
    for cell in matrix.get("cells", []):
        if cell.get("status") != "works":
            continue
        method = method_scope_map["methods"].setdefault(cell["method_id"], {"one_of": []})
        if cell["scope_id"] == "public":
            method.clear()
            method["public"] = True
        elif expanded := expand_scope_set(cell["scope_id"]):
            method.setdefault("all_of", []).extend(expanded)
        elif not method.get("public"):
            method["one_of"].append(cell["scope_id"])
    for method in method_scope_map["methods"].values():
        if "one_of" in method:
            method["one_of"] = sorted(set(method["one_of"]))
            if not method["one_of"]:
                del method["one_of"]
        if "all_of" in method:
            method["all_of"] = sorted(set(method["all_of"]))
    write_json(METHOD_SCOPE_MAP, method_scope_map)
    print(f"method-scope-map methods={len(method_scope_map['methods'])}")


def main() -> int:
    capabilities = load_capabilities()
    services = sorted(capabilities.get("probe_plans", {}))
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", choices=services, default=services[0])
    parser.add_argument("--method")
    parser.add_argument("--scope")
    args = parser.parse_args()
    probe_service(args.service, args.method, args.scope)
    build_matrix()
    build_method_scope_map()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
