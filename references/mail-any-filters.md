# Mail `any` Filters

Use this when a Yandex Mail workflow needs one logical filter made from multiple OR branches, such as collecting receipts from many OFD sender domains into one incoming directory.

## Config shape

```json
{
  "mail": {
    "filters": {
      "payment_receipts": {
        "enabled": true,
        "any": [
          { "sender": "receipts-a.example" },
          { "sender": "receipts-b.example" }
        ]
      }
    }
  }
}
```

Semantics:

- `mail.filters.<name>.any` is an OR list.
- Each branch is the same AND filter shape as a normal named filter: `sender`, `subject`, `since_date`, and `before_date`.
- All branches write under one logical directory: `{data_dir}/incoming/<filter>/`.
- Branch cursor state belongs in the normal mail state file: `{data_dir}/{mail.state_file}` (default `{data_dir}/state.json`), directly inside the existing account bucket `filters.<filter>.accounts.<account>` as `sha256:...` keys. Do not create or use `{data_dir}/incoming/<filter>/state.json` for cursors; `incoming/<filter>/` is output data, not cursor state.
- Branch state must be integrated into the existing account bucket, not a parallel state subsystem. Do not add wrappers such as `branches`, do not add branch-specific helper layers when direct use of `_get_account_state()` / `_save_state()` is enough, and do not replace the existing account bucket shape.
- Preserve normal account cursor fields for `any` filters as well: update `last_uid`, `last_check`, and `last_received_date` in the same bucket alongside the `sha256:...` branch keys. A prod-like account bucket may contain both normal cursor keys and branch hash keys.
- Preserve account buckets for all configured/resolved accounts when surgically clearing one filter; remove only the affected filter entry or affected branch keys, not sibling filters or sibling accounts.
- Branch keys are deterministic hashes of canonical compact JSON for that branch.
- Branch cursor values use three states: missing key = branch was never checked; `null` = branch was checked and had no matching message in the checked UID range; integer UID = latest locally verified match for that branch.
- `--filter <name>` runs exactly the named filter, even if it is disabled for bare runs.
- Raw CLI overrides (`--sender`, `--subject`, dates, `--uid`) are ad-hoc and must not advance persistent named-filter cursors.
- `--dry-run` must not create or mutate branch state.

## Verification pattern

After editing a local `config.agent.json` filter:

1. Validate account discovery from the same CWD/data dir:
   `python3 <skill>/scripts/oauth_setup.py --data-dir <data_dir> --accounts list`
2. Dry-run one branch/filter without persistence:
   `python3 <skill>/mail/scripts/fetch_emails.py --data-dir <data_dir> --filter <filter> --account <alias> --dry-run --num 1`
3. Confirm the JSON includes `dry_run: true`, the expected `filter`, and plausible message metadata.
4. Confirm no branch state was created or changed by dry-run.
5. Run the checked-in mail/schema tests when changing the implementation or schema.
6. For PR writeups or public issue comments, include live validation only in redacted/general form: mention counts, timing, two-account coverage, state shape, and absence of pending failures, but do not include configured account aliases, real message UIDs, local paths, buyer/seller names, or receipt contents.

## Example use: OFD receipt collection

For fiscal receipt discovery, keep the Yandex Mail filter broad and sender-domain based. Do not add guessed subject keywords or specific mailbox addresses unless source evidence requires it. Put all sender-domain branches under one logical filter such as `payment_receipts`, then downstream accounting code can consume one incoming tree.

## Implementation invariant: one search, then local branch matching

For `any` branches that are plain sender domains, do not run one IMAP search per domain. Build one nested IMAP `OR` search over the domain `FROM` criteria, fetch each matching message once, then locally evaluate which branches match the fetched metadata and advance every matching branch cursor. A message may match multiple branches; that is valid and should advance multiple branch state entries.

Do not flatten full email-address sender filters into this sender-domain OR path. Keep the existing `local_part, domain_part = sender.split("@", 1)` workaround for Yandex IMAP full-address `FROM` quirks in the fallback path so existing address-based filters keep their behavior.

## Branch state model and new-branch backfill

Treat `any` branch state as a high-water model integrated into the existing account cursor bucket, not as independent per-branch low-water loops:

- Derive the branch-state map from `sha256:...` keys already present in `filters.<filter>.accounts.<account>`; do not add helper layers that read/write another state file or nested object.
- Compute the filter high-water UID as the maximum numeric UID across branch state values. Ignore missing and `null` values.
- Main search starts after the filter high-water UID, not after the minimum branch UID. This prevents an old overlapping branch from consuming `--num 1` with a duplicate already-seen UID.
- Missing branch key means the branch was added or never checked. Before the main search, run a bounded backfill for only missing branches up to the current high-water UID, then record `null` for missing branches that were checked but did not locally match.
- `null` means checked/no match and should not force future historical rescans; only a missing key triggers bounded backfill.
- After processing fetched messages, update every checked branch carefully: matching branches get the message UID; non-matching checked branches get `null` only if they do not already hold an integer UID. Never overwrite an existing numeric branch UID with `null` just because a later fetched message did not match that branch.
- Also update the normal account cursor fields (`last_uid`, `last_check`, `last_received_date`) for `any` filters using the same existing code path/semantics as flat filters. The branch hashes are additional cursor keys, not a replacement for the account cursor.

## Pitfalls found during OFD receipt testing

- If production data contradicts an issue proposal, treat the production state shape as binding and the issue text as stale design context. In this session, issue #43 proposed `{data_dir}/incoming/<filter>/state.json`; the accepted design is instead the existing shared mail state file with branch hash keys embedded directly in `filters.<filter>.accounts.<account>`.
- When the user points at a real production state example, preserve every structural cue in it: shared `state.json`, `filters -> <filter> -> accounts -> <account>`, normal cursor fields, and sibling account buckets.
- Do not implement OR branch cursors as a parallel state subsystem. Use `_get_account_state()` and existing `_save_state()` flow; derive branch cursor values by filtering the account bucket for `sha256:` keys.
- Do not treat `any` as N independent fetch loops when the user expects one logical OR filter. If conditions are OR alternatives for one sender-domain stream, build/evaluate one logical query/result set first, deduplicate by UID once, then apply `--num` to the unified result.
- Do not use the minimum per-branch cursor as the start UID for an `any` filter. Use the maximum numeric UID as filter high-water; handle newly added branches with bounded backfill to that high-water and `null` for checked/no-match.
- Do not advance a branch merely because it was included in the unified OR query; advance it only after local metadata verification says that branch matches. If local matcher mirrors IMAP `FROM` substring semantics, `<noreply@receipts-a.example>` also matches an `example` branch; preserve that existing numeric UID on later non-matching messages instead of resetting it to `null`.
- When testing with `--num 1`, show the actual saved message directory/meta and the state file before starting profiling. If `fetched_total` increments but no new message directory appears, report that discrepancy immediately and inspect cursor/match logic first.
- After a flawed run pollutes state, reset or surgically remove only the affected filter/account/branch cursor before retesting; otherwise later runs can falsely appear correct or skip legitimate historical messages. When the user points to a prod state file, treat that exact structure as the compatibility contract before changing code: inspect the existing `_get_account_state()` / `_save_state()` flow and extend it, rather than inventing a new storage location or wrapper.
