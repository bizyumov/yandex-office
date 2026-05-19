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
