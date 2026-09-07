# Issue 61 — approved documentation shorthand

Source: issue.md and operator instructions in Telegram topic 225299: use YO, follow GitMark, explicitly waive paths containing spaces; implement now.

AC1: Active executable examples use `$YO/<script>` with one `YO="python3 <full-path-to-yandex-office>"` initialization per independently readable document.
AC2: Bash expands the approved no-space path and preserves separate quoted arguments and current working directory.
AC3: No runtime Python changes; historical CHANGELOG and TODO records and non-command file coordinates remain unchanged.
AC4: Documentation tests, shell expansion regression, diff checks and secret scan pass. Publish a scoped PR referencing #61.

No functions, arrays or runtime path changes. Shared installation remains unchanged pending merge. Baseline a5edc78269f11da163ab4b598774bcf55720f1b4; clean isolated worktree.
