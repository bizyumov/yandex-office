# Config, Data, And Tests

## Shared Configuration

All Yandex sub-skills use the same two-level config:

- skill root `config.skill.json` for shared defaults
- `{data_dir}/config.agent.json` for local runtime overrides
- runtime resolves `{data_dir}` to `./yandex-data` by default
- scripts that support `--data-dir` can use an explicit external path instead

Managed OAuth secrets are separate from runtime data:

- canonical auth path: `~/secrets/yandex-office`
- legacy migration source: `{data_dir}/auth`
- account token files: `~/secrets/yandex-office/{alias}.token`
- pending screen-code state: `~/secrets/yandex-office/oauth-code-flow.json`

Authorization reads use the canonical file first. When it is absent, the auth
layer checks the corresponding legacy file and moves it to the canonical path.
Successful migration prints a token-safe `WARNING` to stderr. New secrets are
never written to `{data_dir}/auth`.

Root `config.skill.json`:

```json
{
  "urls": {
    "oauth": "https://oauth.yandex.ru/authorize",
    "disk_api": "https://cloud-api.yandex.net",
    "telemost_api": "https://cloud-api.yandex.net/v1/telemost-api"
  },
  "imap": { "server": "imap.yandex.com", "port": 993 },
  "mail": {
    "since": "off",
    "filters": {
      "telemost": {
        "sender": "keeper@telemost.yandex.ru"
      }
    },
    "fetch": { "sleep_seconds": 0.5 },
    "state_file": "state.json"
  }
}
```

Local runtime override example `{data_dir}/config.agent.json`:

```json
{
  "mail": {
    "filters": {
      "telemost": {
        "sender": "keeper@telemost.yandex.ru"
      },
      "forms": {
        "sender": "forms@yandex.ru",
        "subject": "New response"
      }
    }
  }
}
```

For the full local config schema contract, including supported fields and
reserved placeholders, see `references/yandex-office-extension.md`.

Config management boundary:

- `oauth_setup.py --accounts list` bootstraps `{data_dir}/config.agent.json`
  and prints managed account aliases only.
- `oauth_setup.py --email <email>` or `oauth_setup.py --account <alias>`
  initializes a local account handle and prints compact account JSON with
  `alias`, optional `email`, and `apps`.
- `oauth_setup.py --app <app_id>` prints an OAuth link for an
  `oauth_apps.catalog` entry such as `mail-readonly`; `--account` is an
  optional hint, not a URL-generation requirement.
- `oauth_setup.py --from-env <ENV_VAR>` imports a token by verified identity.
- Edit `{data_dir}/config.agent.json` for local runtime settings such as
  `mail.filters`. There is currently no dedicated CLI for those settings.

Account aliases and OAuth state are managed by the setup script and runtime
auth layer. Agent config contains local app catalog overrides and
local runtime settings only; new bootstrap and token intake do not create
account inventory in config.

Mail filter notes:

- configured entries under `mail.filters` are peer filters such as `telemost` and `forms`
- legacy top-level keys like `mail.filters.sender` are still upgraded in-memory into `mail.filters.telemost`
- named filters support `enabled: false`; bare runs execute all enabled filters
- named filters may use `any: [...]` for OR-style branch filters; each branch supports the same `sender`, `subject`, `since_date`, and `before_date` fields, while branch cursor state is stored in the normal mail state file `{data_dir}/{mail.state_file}` (default `{data_dir}/state.json`) directly in the existing account bucket `filters.<filter>.accounts.<account>` as `sha256:...` keys alongside normal cursor fields such as `last_uid`, `last_check`, and `last_received_date`; do not add a `branches` wrapper or a filter-local state file
- filter keys must be lowercase English schema keys because they are also used as incoming subdirectory names
- `default` is reserved for ad-hoc one-off runs and must not be used as a configured filter key
- `python3 <full-path-to-yandex-office>/mail/scripts/fetch_emails.py --filter <name>` runs exactly that named filter, even if it is disabled for bare runs
- `python3 <full-path-to-yandex-office>/mail/scripts/fetch_emails.py --account <alias>` selects the token-backed account resolved by `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --accounts list`
- raw CLI overrides such as `--sender`, `--subject`, `--since-date`, `--before-date`, and `--uid` are treated as ad-hoc, do not advance persistent cursors, and search account history by default when no `--filter` is selected
- `--uid <n>` fetches exactly one message, skips filter search logic, and requires `--account` when multiple accounts are available
- `--preview-body` with `--dry-run` includes a `body` object for matching messages without writing incoming files; without it, dry-run fetches headers only
- sender and subject filters are literal IMAP substring matches; no extra query language is implemented
- large dry-run result sets spill into `{data_dir}/latest-query/`; the next spilled run replaces the previous artifact, so copy it elsewhere if you need to keep it

## Regression Tests

Run the checked-in regression suite from the repo root:

```bash
<full-path-to-yandex-office>/scripts/test_regression.sh
```

## Data Directory

Runtime data lives outside the repo at `{data_dir}/`:

```text
{data_dir}/
├── incoming/           # mail writes here
├── state.json          # UID/date tracking keyed by filter and account
├── meetings/           # telemost output (bucketed by month)
│   └── 2026-02/
│       └── 2026-02-24_18-19_alex_1000349120/
│           ├── transcript.txt
│           ├── summary.txt
│           └── meeting.meta.json
├── archive/            # Processed email dirs
└── forms/              # forms export output
    └── {form_id}/
        ├── responses_2026-03-03_080512.xlsx
        └── meta.json
```
