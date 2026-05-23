# Yandex Mail IMAP SUBJECT ё/е normalization

## When this matters

Use this note when debugging Yandex Mail IMAP searches or named mail filters whose `subject` contains Russian `ё`/`Ё`, especially filters that should match messages whose visible subject contains `ё` but IMAP search returns nothing or returns overly broad results after relaxing the subject.

## Durable finding

Yandex IMAP SUBJECT search can behave as if subject terms are indexed with `ё` folded to `е`.

A practical fix is:

- keep the human-readable configured subject exact, e.g. `Счёт на оплату`;
- before constructing IMAP `SUBJECT "..."` criteria, normalize the search term with `Ё → Е` and `ё → е`;
- for local branch matching against fetched metadata, compare subjects after the same fold plus casefold.

## Regression shape

Add/keep tests for both boundaries:

- `_search_emails(..., subject="Счёт на оплату")` should pass UTF-8 IMAP criteria containing `SUBJECT "Счет на оплату"`;
- `_branch_matches_meta({"subject": "Счёт на оплату"}, {"subject": "Счет на оплату ..."})` and the reverse direction should both match.

## Verification pattern

After patching logic, restore the precise configured subject instead of leaving a broad workaround like `на оплату`, then run a bounded dry-run for the named filter, for example:

```bash
python3 <full-path-to-yandex-office>/mail/scripts/fetch_emails.py --account <alias> --filter <filter_name> --dry-run
```

Verify the spill JSON includes the expected precise subjects and that no state was persisted.
