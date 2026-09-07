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

## Yandex-office Proof-loop Requirements

- Issue bodies are contracts for proof-loop work. When a repo-task-proof-loop
  task is grounded in GitHub issues, download every related issue body and
  comments in full as local Markdown references under the task artifacts before
  freezing the spec. Cite the issue reference files in the spec. Unless the user
  explicitly waives or narrows an issue, each related issue is part of the
  implementation contract.
- Resolve vague proof-loop wording before freeze. Draft specs must not leave
  important behavior behind words like "may", "could", "if available", "where
  practical", "such as", or bare parameter names. Replace them with concrete
  defaults, allowed values, required/error behavior, dependencies, evidence
  expectations, and explicit user-waiver points before asking for approval.
- Upload performance tests use local source fixtures. For upload-performance
  work, select explicit local source files or generated local fixtures. Do not
  scan a remote/private storage inventory to find files to upload unless the
  user asks for remote inventory analysis. Record fixture paths, sizes, target
  paths, cleanup policy, and whether the files are non-sensitive or approved by
  the user for live upload.
- Separate proof from duplicated code. When a task requires separate auth
  surfaces, scopes, path prefixes, tenants, or providers, keep docs, tests,
  evidence, and capability metadata distinct, but reuse implementation code
  unless a real provider/API difference requires a split. Do not use separate
  proof surfaces as an excuse to bloat the codebase.

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
