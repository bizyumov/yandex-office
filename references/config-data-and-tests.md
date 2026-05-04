# Config, Data, And Tests

## Shared Configuration

All Yandex sub-skills use the same two-level config:

- skill root `config.skill.json` for shared defaults
- `{data_dir}/config.agent.json` for agent-specific overrides
- runtime resolves `{data_dir}` to `./yandex-data` by default
- scripts that support `--data-dir` can use an explicit external path instead

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

Agent override example `{data_dir}/config.agent.json`:

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

Config management boundary:

- Run `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py` with no
  arguments to bootstrap `{data_dir}/config.agent.json`.
- Run `scripts/oauth_setup.py --email <email> --account <alias>` for account
  alias initialization.
- Run `scripts/oauth_setup.py --app <app_id>` or `scripts/oauth_setup.py
  --from-env <ENV_VAR>` for OAuth intake.
- Edit `{data_dir}/config.agent.json` for agent-specific settings such as
  `mail.filters`. There is currently no dedicated CLI for those settings.

Account aliases and OAuth state are managed by the setup script and runtime
auth layer. Agent config contains agent-specific app definitions and
settings only; legacy `accounts` / `mailboxes` entries may be read as a
compatibility view, but new bootstrap and token intake do not create account
inventory in config.

Mail filter notes:

- configured entries under `mail.filters` are peer filters such as `telemost` and `forms`
- legacy top-level keys like `mail.filters.sender` are still upgraded in-memory into `mail.filters.telemost`
- named filters support `enabled: false`; bare runs execute all enabled filters
- filter keys must be lowercase English schema keys because they are also used as incoming subdirectory names
- `default` is reserved for ad-hoc one-off runs and must not be used as a configured filter key
- `mail/scripts/fetch_emails.py --filter <name>` runs exactly that named filter, even if it is disabled for bare runs
- raw CLI overrides such as `--sender`, `--subject`, `--since-date`, and `--before-date` are treated as ad-hoc, do not advance persistent cursors, and search mailbox history by default when no `--filter` is selected
- sender and subject filters are literal IMAP substring matches; no extra query language is implemented
- large dry-run result sets spill into `{data_dir}/latest-query/`; the next spilled run replaces the previous artifact, so copy it elsewhere if you need to keep it

## Regression Tests

Run the checked-in regression suite from the repo root:

```bash
./scripts/test_regression.sh
```

## Data Directory

Runtime data lives outside the repo at `{data_dir}/`:

```text
{data_dir}/
├── incoming/           # mail writes here
├── state.json          # UID/date tracking keyed by filter and mailbox
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
