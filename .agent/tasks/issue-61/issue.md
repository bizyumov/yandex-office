# Issue 61

<!-- issue-audit-current-state -->
## Current-state audit — 2026-09-07

**Disposition:** Not implemented; the proposed shell abbreviation needs portability validation.

**Verified baseline:** `main` at `a5edc78269f11da163ab4b598774bcf55720f1b4`.

### Delivered changes and related PRs
Current SKILL.md and disk/disk.md still repeat <full-path-to-yandex-office>. PR #42 establishes the account-first examples; PR #66 adds the canonical disk.py command surface.

### Remaining scope / acceptance clarification
Evaluate a quoted skill-root variable or shell function rather than blindly adopting Y="python3 <path>" with $Y/scripts syntax. Test paths containing spaces and the documented shell. Preserve absolute-script execution and CWD-based data_dir behavior. Update examples consistently only after the chosen syntax is validated; do not change runtime path resolution.

The original report below is retained for provenance; obsolete paths, token formats and implementation-absence claims are superseded by this audit. This update does not close the issue or claim unperformed live verification.

---

Consider updating skill docs to uniformly use

`Y='python3 <full-path-to-yandex-office>'`

so that 

Run first: `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py --accounts list`

becomes 

Run first: `$Y/scripts/oauth_setup.py --accounts list`

Getting rid of repeated `<full-path-to-yandex-office>` saves tokens and improves readability

## Comments
