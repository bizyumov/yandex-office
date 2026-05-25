# Managed Auth Extension Notes

Use this reference only when auditing or extending low-level Yandex API methods.
Workflow commands must resolve account first and use sub-skill docs.

Runtime auth lives on decorated methods:
`@yandex_api_method(method_id, public=True)`,
`@yandex_api_method(method_id, one_of=[...])`, or
`@yandex_api_method(method_id, all_of=[...])`. Callers do not pass tokens.

The wrapper resolves managed tokens from token `client_id` plus app-config
scopes, orders candidates by `good_at`, marks GOOD only after normal return,
marks BAD only for `403 ForbiddenError`, and blocks before the API call when no
candidate is eligible.

## Unknown OAuth Client IDs

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
