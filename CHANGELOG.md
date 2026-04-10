# Changelog

All public `yandex-office` skill releases use the `YYYY.MM.DD` version format.

## 2026.04.10

### Changed

- established flat mail filter configuration under `mail.filters.<name>`
- reserved `default` for ad-hoc runtime-only mail queries
- upgraded legacy `mail.filters.sender` handling to the `telemost` filter
- documented the shared config flow: `config.json` -> `{data_dir}/config.agent.json` -> `state.json`
- documented the release policy for dated skill releases

### Fixed

- mail bare runs now execute all enabled configured filters
- `--filter NAME` now runs exactly that filter even if disabled
- ad-hoc mail queries now search mailbox history by default instead of inheriting a hidden stored cursor
- per-filter mail state is isolated by filter and mailbox
- saved mail output is separated under `incoming/<filter>/...`
- Yandex IMAP UTF-8 sender/subject searches now use `SEARCH UTF-8` with sequence-to-UID remapping
- heavy dry-run result sets now spill to an ephemeral file with an explicit retention warning

### Migration Notes

- configured mail filters must live directly under `mail.filters`
- `mail.filters.profiles` is removed
- configured filter key `default` must not be used
- use `telemost` as the legacy/base Telemost filter key

### Verification

- `pytest -q mail/scripts/test_fetch_emails.py common/tests`
- `./scripts/test_regression.sh`
- `python3 -m compileall common scripts mail`
- live mailbox checks against the real `work` mailbox
