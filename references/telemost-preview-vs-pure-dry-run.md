# Telemost check modes: plain dry-run vs dry-run + preview-body

This note exists to avoid semantic confusion in Telemost checks.

## Use-cases

- **Plain check-only (`--filter telemost --dry-run`)**
  - Non-persistent, side-effect safe.
  - Fetch scope = configured sender/subject/date filters of the named filter.
  - IMAP fetches only headers in preview rows.
  - Output `pending` rows contain minimal metadata (uid/account/sender/subject/timestamp/filter).

- **Body preview (`--filter telemost --dry-run --preview-body`)**
  - Also non-persistent.
  - Fetches full RFC822 into memory to provide `body.text` / `body.html` for matching messages.
  - Use this only when searching for markers such as full transcript mentions, meeting links, audio/video links.
  - Can be combined with `--from-uid` and `--num` for bounded backfill slices.

## Important pitfall

- These two modes are **not equivalent** for row counts and payload shape.
  A bounded body-preview run (`--num`, `--from-uid`) is a deliberate sample window, not a full canonical Telemost count.

## Constraint

- `--preview-body` is valid only with `--dry-run` (parser rejects otherwise).
