# OAuth screen-code test/debugging notes

Use this when testing or debugging `oauth_setup.py --code-flow` behavior with several pending Yandex OAuth links.

## Preserve the test state

- Do not clear or rewrite `{data_dir}/auth/oauth-code-flow.json` during a live test unless the user explicitly asks. The pending registry is the evidence trail for issued links and their order.
- If a registry reset is required, first copy it to a timestamped backup and say so before continuing.
- Do not regenerate a full batch of links after a failed code unless the user asks; doing so changes the ordered pending set under test.

## Completion command discipline

- If the user asks a code to land in a specific alias, pass that alias on completion:
  `python3 <skill>/scripts/oauth_setup.py --account <alias> --code-flow complete --code <confirmation-code>`
- Treat the command's stdout/stderr as the primary result. Report the complete non-secret output exactly, including `Warnings:` and the final resolved alias line.
- After completion, verify with:
  `python3 <skill>/scripts/oauth_setup.py --account <alias>`
  and, when relevant, check the resolved alias mentioned by the command output.

## Interpreting `invalid_grant` during batch tests

In a batch registry, a user may send codes in any order. A code can be valid for a later pending flow while earlier pending flows reject it. Therefore:

- Do not infer from one `invalid_grant` / `Code has expired` response that the user's code was actually expired.
- First establish which pending entry was tried, from CLI debug output if available, or from code inspection plus registry order if no debug exists.
- If the CLI now continues over `invalid_grant` responses, the final message `Confirmation code did not match any pending authorization` means no remaining pending entry accepted that code.

## Evidence format for frustrated test sessions

When the user asks "what happened" or challenges an OAuth result, answer as an evidence log:

1. exact command run;
2. complete stdout/stderr, redacting only secrets;
3. exit code;
4. registry state before/after (app IDs, created/expires, not code verifiers);
5. account summaries before/after via `--account <alias>`;
6. clear conclusion separating facts from interpretation.

Do not inspect or print bearer token values. It is acceptable to report token file path, existence, permissions, email, app IDs, and client IDs.