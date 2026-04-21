# Runtime method-scope-map integration analysis

Status: analysis note for GH38 deterministic permission reasoning.

## Current Finding

GH38 delivered the empirical capability map, but current runtime token selection
does not use it yet.

Current runtime behavior:
- callers pass broad hardcoded `required_scopes` lists into `resolve_token()`
- `resolve_token()` reads one canonical `token.<service>` value
- token metadata is diagnostic and service-scoped
- callers choose the service token before the exact API method is represented

This means `capabilities/method-scope-map.json` is currently a diagnostic and
documentation artifact, not the runtime source of truth for token choice.

## Required Design Change

Runtime calls must identify the concrete capability method before token
resolution.

New runtime shape:

```text
caller operation
  -> api_method id
  -> method-scope-map requirement
  -> token candidates for the Yandex account
  -> best matching token
  -> API call
  -> runtime response remains final truth
```

`method-scope-map.json` becomes authoritative for choosing which already stored
token is suitable for a method. It must not become an absolute guarantee that
the API call will succeed, because account settings, ownership, object state,
organization role, mailbox mode, and service-side policy can still fail after
OAuth scope authorization.

## New Runtime Module

Add a shared module, for example `common/capabilities.py`.

Responsibilities:
- load `capabilities/method-scope-map.json`
- validate `schema_version` and generated structure
- expose `get_method_requirement(method_id)`
- expose `token_satisfies_method(token_scopes, method_id)`
- expose `choose_token_for_method(token_candidates, method_id)`

Requirement forms:

```json
{"public": true}
{"one_of": ["cloud_api:disk.read", "cloud_api:disk.app_folder"]}
{"all_of": ["cloud_api:disk.read", "cloud_api:disk.write"]}
```

Selection rules:
- `public: true`: no OAuth token required; caller may still choose OAuth for
  service-specific reasons, such as Telemost recording Disk links.
- `one_of`: choose any token whose stored scope set intersects the list.
- `all_of`: choose a token whose stored scope set contains every listed scope.
- no map entry: return structured `method_not_mapped`, do not guess scopes.

## Token Candidate Model Gap

The current token file format is not enough for deterministic choice when an
account has multiple tokens that cover the same service differently.

Current shape:

```json
{
  "email": "user_at_example",
  "token.disk": "y0_...",
  "token_meta": {
    "token.disk": {
      "client_id": "...",
      "app_id": "disk-full",
      "scopes": ["cloud_api:disk.read", "cloud_api:disk.write"]
    }
  }
}
```

This supports one active token per service key. It cannot represent both
`disk-readonly` and `disk-full` as selectable candidates for the same account.

Required storage evolution:
- keep legacy `token.<service>` keys for compatibility
- add a candidate collection that can hold more than one token per account
- each candidate must store token value plus metadata:
  - `client_id`
  - `app_id` when known
  - `scopes`
  - `services`
  - verified Yandex account email
- service keys may remain aliases/defaults pointing at candidate ids

Example target shape:

```json
{
  "email": "user_at_example",
  "token.disk": "y0_legacy_or_default",
  "token_candidates": {
    "disk-readonly": {
      "token": "y0_...",
      "client_id": "...",
      "app_id": "disk-readonly",
      "scopes": ["cloud_api:disk.read"],
      "services": ["disk"]
    },
    "office-core": {
      "token": "y0_...",
      "client_id": "...",
      "app_id": "office-core",
      "scopes": ["calendar:all", "cloud_api:disk.read", "cloud_api:disk.write"],
      "services": ["calendar", "disk", "mail", "telemost"]
    }
  },
  "token_aliases": {
    "token.disk": "office-core"
  }
}
```

## `resolve_token()` Change

Extend `resolve_token()` without breaking existing callers.

Proposed parameters:

```python
resolve_token(
    account=...,
    skill=...,
    data_dir=...,
    config=...,
    method_id="disk.resources.get.disk",
    required_scopes=None,  # legacy fallback only
)
```

Behavior:
- if `method_id` is provided, load method requirement from
  `method-scope-map.json`
- build token candidates from `token_candidates` plus legacy `token.<service>`
- choose the narrowest matching token by method requirement
- return `ResolvedToken` with selected candidate metadata
- if no candidate matches, raise `TokenResolutionError` with:
  - `method_id`
  - required method-scope-map entry
  - available candidate app ids/scopes
  - onboarding remediation hint
- if `method_id` is absent, keep current service-token behavior as compatibility

Do not use `required_scopes` as the new source of truth. It should remain only a
temporary compatibility path while callers migrate to method ids.

## Caller Migration

Each API call site must pass a method id instead of a broad scope list.

Examples:
- Calendar list events:
  - `calendar.caldav.principal`
  - `calendar.caldav.calendars`
  - `calendar.caldav.report.date_search`
- Calendar create event:
  - `calendar.caldav.event.put`
- Telemost create conference:
  - `telemost.conferences.create`
- Telemost read conference:
  - `telemost.conferences.get`
- Mail fetch:
  - `mail.imap.select`
  - `mail.imap.search`
  - `mail.imap.fetch`
- Forms list/answer export:
  - use the exact `forms.*` method id from `method-scope-map.json`
- Tracker:
  - use the exact `tracker.*` method id from `method-scope-map.json`
- Disk:
  - split path-shape-sensitive calls:
    - `disk.resources.get.disk`
    - `disk.resources.get.app_folder`
    - `disk.resources.publish.put.disk`
    - `disk.resources.publish.put.app_folder`

Disk is the most important migration target because one upstream endpoint can
map to different method ids depending on path namespace and capability shape.

## Runtime Policy

Deterministic permission reasoning means:
- before choosing a token, use `method-scope-map.json`
- when several stored tokens are available, choose a token whose scopes satisfy
  the method entry
- prefer the narrowest matching token
- explain failures using the same method entry

It does not mean:
- block every API call before runtime
- assume OAuth scopes are enough for success
- ignore service-specific runtime constraints such as mailbox settings, org
  roles, object ownership, or public/private resource state

## Status Against GH38

The capability matrix is delivered.
The runtime link for deterministic token choice is not implemented yet.

To satisfy deterministic permission reasoning end to end, GH38 needs a follow-up
implementation batch that adds:
- `common/capabilities.py`
- multi-token candidate storage or equivalent selectable token inventory
- `resolve_token(method_id=...)`
- method-id migration in current callers
- tests proving token choice from `method-scope-map.json`
