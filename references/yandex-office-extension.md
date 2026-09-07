# yandex-office Extension Reference

Use this reference only when auditing or extending shared yandex-office runtime
mechanics. Workflow commands must resolve account first and use sub-skill docs.

## Table of Contents

- [Managed Auth Extension](#managed-auth-extension)
- [Script Import Bootstrap](#script-import-bootstrap)
- [Config Extension](#config-extension)

## Managed Auth Extension

Runtime auth lives on decorated methods:
`@yandex_api_method(method_id, public=True)`,
`@yandex_api_method(method_id, one_of=[...])`, or
`@yandex_api_method(method_id, all_of=[...])`. Callers do not pass tokens.

The wrapper resolves managed tokens from token `client_id` plus app-config
scopes, orders candidates by `good_at`, marks GOOD only after normal return,
marks BAD only for `403 ForbiddenError`, and blocks before the API call when no
candidate is eligible.

### Unknown OAuth Client IDs

Token import and dispatch use Yandex as the source of truth for unknown OAuth
`client_id` scope metadata. After a token is verified and its `client_id` is
known, if that `client_id` is absent from the merged app catalog or is marked
with `scopes: ["unresolved"]`, managed auth resolves metadata with exactly one
plain unauthenticated request to:

`https://oauth.yandex.com/client/{client_id}/info?format=json`

Only the endpoint's JSON `scope` field may populate the app's resolved
`scopes`. If the response includes an `id`, it must match the requested
`client_id`. The endpoint's `name` may be used as the local app name.

Forbidden sources for this resolution:

- operator-entered permission descriptions
- local atomic client registries or cached guesses
- API360 service application registries
- OAuth-token-authenticated metadata calls
- browser profiles, cookies, or CAPTCHA-solving workarounds
- retries, alternate endpoints, or fallback URLs

CAPTCHA JSON is not scope metadata. During import, CAPTCHA JSON creates or
updates an agent-local app entry with `scopes: ["unresolved"]` and emits a
warning. Before a token bound to an unresolved app can satisfy decorated method
auth, managed auth must resolve the same `client_id` from the same Yandex
client-info endpoint and replace `["unresolved"]` with the returned scope list.
Non-CAPTCHA metadata failure blocks unknown-client import or provider use
without writing a resolved app definition.

Verification sources:

- `capabilities/methods.json`: method inventory, classification, local sources.
- `capabilities/method-scope-map.json`: proven `public`, `one_of`, or `all_of`
  auth shape.
- `capabilities/matrix.json`: denial evidence.
- `capabilities/README.md`: generated map provenance.
- `references/yandex-office-auth-principles.md`: auth model.

Run:

```bash
python3 capabilities/audit-method-auth.py
```

Runtime proof should show managed dispatch evidence such as `good_at` updates
and no legacy raw-token paths like `token_meta` or `token.<service>`.

Example:

```python
@yandex_api_method("disk.resources.get.disk", one_of=["cloud_api:disk.read"])
def _api_get_resource(ctx: YandexApiContext, endpoint: str, path: str) -> dict:
    return request_json(ctx, "GET", endpoint, params={"path": path})
```

Out of bounds:

- `token` parameters on API methods.
- raw-token environment fallbacks or raw-token CLIs.
- `auth_call(...)` wrappers.
- parallel auth registries.
- per-method response handling.
- service-specific HTTP subclasses.

Low-level methods call `request_json()`. Runtime API responses are final truth;
scopes guide onboarding and remediation but must not become premature runtime
blockers.

## Script Import Bootstrap

Command scripts in this repository are documented and executed by full file path,
for example `python3 <full-path-to-yandex-office>/mail/scripts/fetch_emails.py`.
They therefore cannot rely on installed packages, `python -m`, or relative
package imports to reach shared runtime code.

Each Python command, library module, or test that imports another repo-root
module must add the repository root with a deterministic `__file__`-relative
bootstrap before repo-local imports:

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
```

Use the number of `os.path.dirname(...)` calls required by the file's location
relative to the repository root. A file directly under `scripts/` uses two
dirname calls; files under `<sub-skill>/scripts/` or `<sub-skill>/lib/` use
three.

After that bootstrap, imports should use repo-root package names such as
`common.config`, `disk.scripts.download`, `telemost.lib.client`, or
`calendars.lib.client`. Do not use `PYTHONPATH` re-exec, `importlib.util`
source loaders, or extra per-module path inserts.

## Config Extension

Root `config.agent.schema.json` is the formal schema for local
`{data_dir}/config.agent.json`. The schema describes local runtime overrides and
custom OAuth app catalog entries only. It does not store account inventory,
tokens, or root skill defaults.

The schema is a contract and documentation surface. Runtime behavior exists only
when code reads the field. If a schema property is not backed by code, its
description must start with `(RESERVED FOR FUTURE USE)`.

Top-level schema sections:

| Path | Status | Description |
| --- | --- | --- |
| `mail` | Supported | Local Mail runtime settings: named filters, throttling, output spill behavior, and state file naming. |
| `disk` | Supported | Local Disk runtime overrides for the optional S3/Object Storage upload bridge. |
| `calendar` | Mixed | Calendar event creation uses local time preference fields and attachment handoff settings; availability/default-calendar placeholders are reserved. |
| `contacts` | Reserved | `(RESERVED FOR FUTURE USE)` Local Contacts settings. |
| `directory` | Reserved | `(RESERVED FOR FUTURE USE)` Local Directory lookup settings. |
| `forms` | Reserved | `(RESERVED FOR FUTURE USE)` Local Forms export and polling settings. |
| `oauth_apps` | Supported | Agent-local custom OAuth app catalog entries discovered or added for this data directory. |

Supported local config fields:

| Path | Description |
| --- | --- |
| `mail.filters` | Named Mail filters keyed by lowercase English schema keys; keys are used for persistent state and incoming subdirectory names. |
| `mail.filters.sender` | `(DEPRECATED) see mail.filters.<name>` Legacy top-level FROM criterion upgraded in memory into `mail.filters.telemost.sender`. |
| `mail.filters.subject` | `(DEPRECATED) see mail.filters.<name>` Legacy top-level SUBJECT criterion upgraded in memory into the Telemost filter. |
| `mail.filters.since_date` | `(DEPRECATED) see mail.filters.<name>` Legacy top-level lower date bound for Mail search, in `YYYY-MM-DD` form. |
| `mail.filters.before_date` | `(DEPRECATED) see mail.filters.<name>` Legacy top-level upper date bound for Mail search, in `YYYY-MM-DD` form. |
| `mail.filters.<name>.sender` | Literal IMAP FROM substring criterion for this named filter. |
| `mail.filters.<name>.subject` | Literal IMAP SUBJECT substring criterion for this named filter. |
| `mail.filters.<name>.since_date` | Lower date bound for this named filter, in `YYYY-MM-DD` form. |
| `mail.filters.<name>.before_date` | Upper date bound for this named filter, in `YYYY-MM-DD` form. |
| `mail.filters.<name>.enabled` | Whether this named filter participates in bare fetch runs; `--filter` can still run disabled filters explicitly. |
| `mail.fetch` | Mail fetch execution settings. |
| `mail.fetch.sleep_seconds` | Pause between real Mail message processing iterations, in seconds; dry-run search-only queries do not use this delay. |
| `mail.output` | Mail output handling for broad dry-run result sets. |
| `mail.output.max_inline_symbols` | Maximum inline output size measured in symbols/characters before Mail writes a spill file. |
| `mail.output.spill_dir` | Directory name under `{data_dir}` where oversized dry-run Mail output is written. |
| `mail.since` | Whether Mail uses state-driven IMAP SINCE filtering for large accounts. |
| `mail.state_file` | Mail state file name under `{data_dir}`; tracks UID/date cursors by account and filter. |
| `disk.s3` | Optional non-secret S3/Object Storage settings for Disk upload staging; credentials stay with the S3 client runtime. |
| `disk.s3.endpoint_url` | S3-compatible endpoint URL, such as `https://storage.yandexcloud.net`. |
| `disk.s3.region` | S3 region name used by the client runtime. |
| `disk.s3.bucket` | S3 bucket used for temporary upload staging; root skill defaults may provide a product default and local config may override it. |
| `disk.s3.prefix` | Object key prefix for temporary upload staging. |
| `disk.s3.presign_ttl_seconds` | Lifetime in seconds for presigned URLs generated in memory. |
| `disk.s3.cleanup_after_disk_import` | Whether temporary S3 objects are deleted after Disk import verification. |
| `disk.s3.multipart_threshold_mib` | Multipart upload threshold in MiB. |
| `disk.s3.multipart_chunk_mib` | Multipart chunk size in MiB. |
| `disk.s3.max_concurrency` | Optional boto3 transfer concurrency limit. |
| `calendar.attachments` | Calendar attachment handoff settings for Disk-backed published-upload links. |
| `calendar.attachments.remote_dir` | Disk directory used for Calendar attachment uploads before publishing them as `ATTACH;VALUE=URI` links. |
| `calendar.timezone` | IANA timezone default for Calendar event creation, such as `Europe/Moscow`; CLI `--timezone` overrides it for one command. |
| `calendar.utc_offset` | Fixed UTC offset default for Calendar event creation: `Z`, `+HH:MM`, or `-HH:MM`; CLI `--utc-offset` overrides it for one command. |
| `oauth_apps.catalog` | Custom OAuth apps keyed by local app id. |
| `oauth_apps.catalog.<app>` | One local OAuth app entry. |
| `oauth_apps.catalog.<app>.client_id` | Yandex OAuth application client id. |
| `oauth_apps.catalog.<app>.scopes` | OAuth scopes granted by this app. |
| `oauth_apps.catalog.<app>.name` | Display name persisted for automatically discovered custom apps. |
| `oauth_apps.catalog.<app>.app_name` | Display name used by configured app catalog entries. |
| `oauth_apps.catalog.<app>.service` | Service or services this app is intended to cover. |
| `oauth_apps.catalog.<app>.is_default` | Whether this local app is the default app for its service. |
| `oauth_apps.catalog.<app>.omit_scope_in_url` | Whether OAuth setup should omit the scope query parameter for this app. |

Reserved local config fields:

| Path | Description |
| --- | --- |
| `calendar.default_calendar` | `(RESERVED FOR FUTURE USE)` Preferred Yandex Calendar name when a command does not specify one. |
| `calendar.business_hours` | `(RESERVED FOR FUTURE USE)` Preferred local business-hours window for availability helpers. |
| `calendar.business_hours.start` | `(RESERVED FOR FUTURE USE)` Business day start time in `HH:MM` local wall-clock format. |
| `calendar.business_hours.end` | `(RESERVED FOR FUTURE USE)` Business day end time in `HH:MM` local wall-clock format. |
| `calendar.slot_granularity_minutes` | `(RESERVED FOR FUTURE USE)` Preferred availability slot size in minutes. |
| `contacts.default_addressbook` | `(RESERVED FOR FUTURE USE)` Preferred address book name for Contacts commands. |
| `contacts.sync_on_startup` | `(RESERVED FOR FUTURE USE)` Whether Contacts workflows should refresh local data at startup when supported. |
| `contacts.cache_ttl_seconds` | `(RESERVED FOR FUTURE USE)` Contacts cache time-to-live in seconds. |
| `contacts.fuzzy_match_threshold` | `(RESERVED FOR FUTURE USE)` Minimum fuzzy-match score for contact name matching. |
| `directory.cache_ttl_hours` | `(RESERVED FOR FUTURE USE)` Directory cache time-to-live in hours. |
| `directory.default_per_page` | `(RESERVED FOR FUTURE USE)` Default Yandex 360 Directory page size for list operations. |
| `directory.search_fuzzy_threshold` | `(RESERVED FOR FUTURE USE)` Minimum fuzzy-match score for Directory search matching. |
| `forms.state_file` | `(RESERVED FOR FUTURE USE)` Forms state file name under `{data_dir}`. |
| `forms.default_format` | `(RESERVED FOR FUTURE USE)` Default response export format for Forms commands. |
| `forms.export` | `(RESERVED FOR FUTURE USE)` Forms export polling settings. |
| `forms.export.poll_interval_seconds` | `(RESERVED FOR FUTURE USE)` Seconds between Forms export polling attempts. |
| `forms.export.max_wait_seconds` | `(RESERVED FOR FUTURE USE)` Maximum seconds to wait for a Forms export to become ready. |

When adding or changing local config:

- Implement the runtime reader in the same change that marks a property
  supported.
- Keep unsupported placeholders marked `(RESERVED FOR FUTURE USE)`.
- Add or update schema tests in `common/tests/test_agent_config_schema.py`.
- Keep account inventory and OAuth tokens out of `config.agent.schema.json`.
- Keep agent-local preferences out of root `config.skill.json`; Calendar
  timezone and UTC offset are explicitly local-only.
