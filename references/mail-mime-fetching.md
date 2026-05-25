# Mail MIME fetching and body/attachment semantics

Use this when changing or auditing `mail/scripts/fetch_emails.py` body, attachment, `--dry-run`, or `--preview-body` behavior.

## Core principle

A fetched message should be preserved as a full, auditable MIME message projection. Do not silently drop a MIME part merely because it has `Content-Disposition`.

## Implementation-status pitfall

When discussing this workflow, be explicit about whether a schema is proposed, present only in a local diff, committed, released, or already present in downloaded `meta.json` data. Do not cite new metadata fields as facts in downloaded examples until the writer has actually produced them. Existing downloaded corpus may still contain only the legacy `attachments` string-list format.

## Body extraction

- Body candidates are textual MIME parts: `text/plain` and `text/html`.
- Treat `Content-Disposition: inline` textual parts as body candidates. Some OFD/Kontur receipts put the only amount-bearing body in inline `text/plain`/`text/html` parts.
- Treat `Content-Disposition: attachment` textual parts as attachments, not the canonical body.
- `multipart/*` parts are containers, not saved as body themselves.
- Keep compatibility: when a text body exists, continue producing `email_body.txt`; when HTML exists, continue producing `email_body.html`; if only HTML exists, text fallback may be generated from HTML as before.

## Attachments and inline file assets

- Real attachments should be saved under their decoded original filename, sanitized only for filesystem safety.
- Do not confuse inline textual bodies with attachments: inline `text/plain` / `text/html` stay body candidates and are represented under top-level `body`.
- Keep the current schema small: all non-body saved MIME file parts belong in the single top-level `attachments` list; do not add separate top-level `attachment_details` or `inline_assets` fields unless the task explicitly changes the schema.
- Inline non-text assets (images, QR codes, logos) are not body text/HTML. If saved, include them in `attachments` with `disposition: "inline"` and `content-id` when present.
- Current reader behavior accepts both `attachments` string items and object items. Current writer behavior should write object items.

## Metadata

`meta.json` should make saved content auditable while keeping only two top-level content fields: `body` and `attachments`.

- `body` remains a separate map for body files, e.g. `{"text": "email_body.txt", "html": "email_body.html"}`. Do not move body files into `attachments`.
- `attachments` contains non-body saved MIME file parts. New items should be objects with hyphenated keys:
  - `original-filename`: decoded filename from the MIME message;
  - `saved-filename`: actual filename written to disk after sanitization and collision handling;
  - `content-type`: MIME content type;
  - `size`: saved payload size in bytes;
  - `disposition`: `attachment`, `inline`, or null/absent;
  - `content-id`: MIME `Content-ID` if present, otherwise null/absent;
  - `part-index`: ordinal index of the MIME part during `msg.walk()` traversal, useful for audit/debug.
- String items in `attachments` are accepted as reader input and normalize as both `original-filename` and `saved-filename`, with other metadata unknown.
- Partial failures should be marked via `partial: true` without losing metadata for successful parts.

Example shape without real filenames or mailbox-specific details:

```json
{
  "body": {
    "text": "email_body.txt",
    "html": "email_body.html"
  },
  "attachments": [
    {
      "original-filename": "<filename-from-message>",
      "saved-filename": "<sanitized-filename-on-disk>",
      "content-type": "application/pdf",
      "size": 12345,
      "disposition": "attachment",
      "content-id": null,
      "part-index": 3
    },
    {
      "original-filename": "<inline-asset-name>",
      "saved-filename": "<sanitized-inline-asset-name>",
      "content-type": "image/png",
      "size": 678,
      "disposition": "inline",
      "content-id": "<content-id-if-present>",
      "part-index": 4
    }
  ]
}
```

## Pitfalls from issue #50 work

- Do not describe proposed metadata as if it already exists in downloaded examples. First verify the current code path and actual `meta.json` output.
- Do not add new top-level metadata entities for attachment classes unless explicitly requested. For this repo, `body` stays separate and all non-body saved MIME file parts go in `attachments`.
- Do not move `email_body.txt` / `email_body.html` into `attachments`; they belong under top-level `body`.
- Current `attachments` writer output uses object items with hyphenated keys (`original-filename`, `saved-filename`, `content-type`, `content-id`, `part-index`). String items in `attachments` remain valid reader input.
- When testing live fetch behavior, prefer exact `--uid` with `--account` and a non-persistent run; verify generated `meta.json`, then remove any test-only incoming directory if it was written into the real data dir.

## Dry-run and preview-body

- Plain `--dry-run` should be a cheap, non-persistent preview: run the same search, fetch headers only, show UID/account/filter/sender/subject/date, write no files, and advance no state.
- `--dry-run --preview-body` is a special non-persistent body preview: it fetches full RFC822 into memory only to return body text/HTML in the JSON preview, writes no files, and advances no state.
- `--preview-body` is valid only with `--dry-run`.
- Do not add extraction-specific flags such as link-only readers when `--uid` can fetch a full message explicitly.

## Regression tests to keep

- inline `text/plain` saves as body;
- inline `text/html` saves as body/HTML;
- `attachment` textual parts do not replace canonical body;
- normal attachments still save under expected filenames;
- new `attachments` entries are metadata objects and legacy string items remain readable;
- duplicate attachment filenames get distinct saved filenames;
- plain `--dry-run` remains header-only;
- `--dry-run --preview-body` returns body in memory without files/state;
- `--preview-body` without `--dry-run` is rejected;
- ordinary plain/html messages without disposition keep existing behavior.

## Verification commands

When changing `fetch_emails.py` MIME/body behavior, run the focused mail tests first and then the package regression gate:

```bash
python3 -m pytest mail/scripts/test_fetch_emails.py
python3 scripts/test_regression.sh
```

If the change touches config/state handling, also include `common/tests/test_agent_config_schema.py`.
