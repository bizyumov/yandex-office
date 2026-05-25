<!-- repo-task-proof-loop:start -->
## Repo task proof loop

For substantial features, refactors, and bug fixes, use the repo-task-proof-loop workflow.

Required artifact path:
- Keep all task artifacts in `.agent/tasks/<TASK_ID>/` inside this repository.

Required sequence:
1. Freeze `.agent/tasks/<TASK_ID>/spec.md` before implementation.
2. Implement against explicit acceptance criteria (`AC1`, `AC2`, ...).
3. Create `evidence.md`, `evidence.json`, and raw artifacts.
4. Run a fresh verification pass against the current codebase and rerun checks.
5. If verification is not `PASS`, write `problems.md`, apply the smallest safe fix, and reverify.

Hard rules:
- Do not claim completion unless every acceptance criterion is `PASS`.
- Verifiers judge current code and current command results, not prior chat claims.
- Fixers should make the smallest defensible diff.
- For broad Codex tasks, bounded fan-out is allowed only after `init`, only when the user has explicitly asked for delegation or parallel agent work, and only when task shape warrants it: use bounded `explorer` children before or after spec freeze, use bounded `worker` children only after the spec is frozen, keep the task tree shallow, keep evidence ownership with one builder, and keep verdict ownership with one fresh verifier.
- This root `AGENTS.md` block is the repo-wide Codex baseline. More-specific nested `AGENTS.override.md` or `AGENTS.md` files still take precedence for their directory trees.
- Keep this block lean. If the workflow needs more Codex guidance, prefer nested `AGENTS.md` / `AGENTS.override.md` files or configured fallback guide docs instead of expanding this root block indefinitely.

Installed workflow agents:
- `.codex/agents/task-spec-freezer.toml`
- `.codex/agents/task-builder.toml`
- `.codex/agents/task-verifier.toml`
- `.codex/agents/task-fixer.toml`
<!-- repo-task-proof-loop:end -->

## yandex-office PR Hygiene

- Before committing or pushing PR work, identify and report the current branch,
  upstream, PR head/base, and whether the user has rescoped the task away from
  that PR. Do not push to a PR branch after rescope unless the user explicitly
  approves that branch as the target.
- Root `SKILL.md` is a first-read router. Propose exact `SKILL.md` changes
  first and wait for explicit approval. Every approved `SKILL.md` edit must
  update the Document Map in the same diff and verify line ranges with
  `nl -ba SKILL.md`.
- Keep low-level extension/auth mechanics out of root `SKILL.md` by default.
  Put implementation guidance in `references/yandex-office-extension.md` unless
  the user explicitly approves exact root `SKILL.md` text.
- Keep release metadata aligned: `VERSION`, top `CHANGELOG.md` entry, README
  current-release block, root `SKILL.md` metadata, and relevant sub-skill
  metadata. Run a version scan before commit.
- Before saying a PR can merge, check GitHub mergeability and a local
  `git merge-tree --write-tree origin/main HEAD`. If conflicts exist, report
  exact files. After resolving, re-check mergeability, branch divergence, and
  checks.
- For code changes, run the project checks before commit/push:
  `python3 -m pytest -q`, `python3 -m py_compile $(rg --files -g '*.py')`,
  `python3 capabilities/audit-method-auth.py`, `python3 capabilities/validate.py`,
  and `git diff --check`.
- Managed auth is the production auth path. Do not add raw-token API
  parameters, side scripts, app-password paths, raw `imaplib`/`smtplib`
  workflow bypasses, or IMAP-scope fallback for SMTP send.

## Yandex-office Calendar Time Context Docs

- Do not add or remove explanatory prose in root `SKILL.md` for Calendar
  timezone/UTC-offset preference work.
- Root `SKILL.md` changes for this work are limited to editing existing Calendar
  CLI examples, if such examples exist.
- Put agent-facing explanation of Calendar `--timezone` / `--utc-offset`
  behavior only in `calendars/calendar.md`.
- Calendar event creation agents must supply either a timezone or UTC offset to
  the CLI, preferably by saving `calendar.timezone` or `calendar.utc_offset` in
  local `{data_dir}/config.agent.json`.
