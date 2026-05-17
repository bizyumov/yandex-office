# Mail IMAP Method Scenarios

This document explains the Mail IMAP capability rows in user-story language.
It separates what Yandex IMAP empirically accepts from what yandex-office should
allow at runtime.

Important design rule:

- `mail:imap_ro` must open mailboxes read-only. In Python `imaplib`, use
  `select(mailbox, readonly=True)`, which sends IMAP `EXAMINE` internally.
- `mail:imap_full` is required for read-write `SELECT` and for any mailbox or
  message mutation.
- Read-only mailbox mode protects the selected mailbox from flag mutation such
  as `STORE \Deleted`, but it does not turn every IMAP command into a read-only
  operation. Commands such as `CREATE`, `DELETE`, `RENAME`, `SUBSCRIBE`,
  `UNSUBSCRIBE`, and `APPEND` are outside the selected-mailbox read-only guard.

The generated `method-scope-map.json` is empirical evidence. Runtime policy must
still enforce the read-only/read-write split below.

## Current yandex-office Usage

The current mail fetcher is read-oriented and uses these IMAP operations:

- `mail.imap.authenticate`: `_connect_imap()` authenticates with XOAUTH2.
- `mail.imap.select`: `_connect_imap()` selects `INBOX`.
- `mail.imap.search`: `_search_emails()` uses `SEARCH` for UTF-8 fallback.
- `mail.imap.fetch`: `_search_emails()` fetches sequence `UID`; message download
  fetches message/header payloads.
- `mail.imap.uid.search`: `_search_emails()` normally uses `UID SEARCH`.
- `mail.imap.uid.fetch`: message download and header inspection use `UID FETCH`.
- `mail.imap.logout`: fetcher cleanup logs out from IMAP sessions.

Current code issue: `mail/scripts/fetch_emails.py` calls `conn.select("INBOX")`
without `readonly=True`. For `mail:imap_ro`, that should be changed to
`conn.select("INBOX", readonly=True)`.

## Readonly Methods

These methods support read-only user stories. They may run with `mail:imap_ro`
only when mailbox selection is forced read-only.

### `mail.imap.authenticate`

User story: connect to a mailbox so yandex-office can read incoming mail.

Examples:

- Fetch new Telemost emails.
- Check whether the OAuth token is valid for IMAP.
- Diagnose whether IMAP + OAuth is enabled for an account.

Current code: used by `_connect_imap()`.

### `mail.imap.capability`

User story: discover which IMAP features the Yandex server advertises.

Examples:

- Confirm whether `UIDPLUS`, `MOVE`, or other optional IMAP extensions exist.
- Decide whether a future client can use server-specific optimizations.

Current code: not currently used.

### `mail.imap.noop`

User story: keep a session alive or cheaply verify that the connection still
works.

Examples:

- Long-running fetch loop wants to avoid reconnecting.
- Health check for an open IMAP session.

Current code: not currently used.

### `mail.imap.logout`

User story: end an IMAP session.

Examples:

- Cleanup after fetching mail.
- Release server-side session resources.

Current code: used by fetcher cleanup paths.

### `mail.imap.list`

User story: list mailbox folders.

Examples:

- Show available folders such as `INBOX`, archive, spam, or custom folders.
- Let a user choose which folder a fetch profile should scan.

Current code: not currently used.

### `mail.imap.lsub`

User story: list subscribed folders.

Examples:

- Show only folders the mailbox owner has chosen to subscribe to.
- Build a lighter folder picker than full `LIST`.

Current code: not currently used.

### `mail.imap.status`

User story: inspect mailbox counters without selecting the mailbox.

Examples:

- Show unread/new-message counts.
- Check `UIDNEXT` or `UIDVALIDITY` for incremental sync decisions.
- Estimate whether a folder has changed before running a heavier search.

Current code: not currently used.

### `mail.imap.select`

User story: open a mailbox before reading messages.

Readonly policy:

- With `mail:imap_ro`, this must be `select(mailbox, readonly=True)`.
- With `mail:imap_full`, read-write selection is allowed only when the workflow
  needs mutation.

Examples:

- Open `INBOX` to search and fetch new mail.
- Open a configured folder for a specific mail filter.

Current code: used by `_connect_imap()`, but currently without `readonly=True`.

### `mail.imap.examine`

User story: explicitly open a mailbox read-only at the protocol level.

Examples:

- Read messages while making mailbox mutation impossible in the selected state.
- Verify that read-only mode blocks `STORE \Deleted`.

Current code: not directly used; `imaplib.select(..., readonly=True)` is the
Python equivalent.

### `mail.imap.check`

User story: ask the server to checkpoint selected mailbox state.

Examples:

- Low-level session maintenance.
- Compatibility testing against an IMAP server.

Current code: not currently used.

Design note: this is not useful for normal mail-fetching workflows, but it does
not directly create/delete messages or folders.

### `mail.imap.close`

User story: close the currently selected mailbox.

Readonly policy:

- Safe only if the mailbox was opened read-only.
- Dangerous after read-write `SELECT`, because IMAP `CLOSE` can permanently
  remove messages already marked `\Deleted`.

Examples:

- End a selected read-only mailbox session.
- In read-write workflows, finalize deletion of messages already flagged
  `\Deleted`.

Current code: not currently used. Prefer `logout` for read-only fetch cleanup.

### `mail.imap.search`

User story: find messages by sender, subject, date, flags, or other criteria.

Examples:

- Find Telemost emails from a sender filter.
- Search messages since a date.
- UTF-8 fallback search for non-ASCII sender or subject values.

Current code: used by `_search_emails()` for UTF-8 fallback.

### `mail.imap.fetch`

User story: read message data by sequence id.

Examples:

- Convert sequence ids to UIDs.
- Fetch headers or full RFC822 message content.

Current code: used by `_search_emails()` and message download paths.

### `mail.imap.uid.search`

User story: find messages by stable UID rather than transient sequence number.

Examples:

- Incremental mailbox sync using `UID > last_seen_uid`.
- Search configured filters without being confused by message sequence shifts.

Current code: used by `_search_emails()`.

### `mail.imap.uid.fetch`

User story: read message data by stable UID.

Examples:

- Download new messages into `incoming/`.
- Fetch headers for dry-run previews.
- Fetch full RFC822 payloads for downstream Telemost processing.

Current code: used by message download and header inspection paths.

## Readwrite Methods

These methods mutate mailbox structure, message state, or mailbox subscription
state. yandex-office should require `mail:imap_full` for them, even when Yandex
accepts some of them with a `mail:imap_ro` token.

Do not describe `mail:imap_ro` as having "full IMAP capabilities." The accurate
picture is narrower and stranger:

- with read-only mailbox selection, selected-message flag mutation such as
  `STORE \Deleted` is blocked;
- mailbox lifecycle commands such as `CREATE` and `DELETE` can still succeed
  with `mail:imap_ro`, because they do not depend on the selected mailbox mode.

A live persistence check confirmed `mail:imap_ro` could create a folder, survive
disconnect/reconnect, appear in `LIST`, and then delete that folder for cleanup.
That proves mailbox lifecycle mutation, not unrestricted read-write message
mutation.

### `mail.imap.create`

User story: create a mailbox folder.

Examples:

- Create an archive folder.
- Create a processing folder such as `Processed/Telemost`.
- Create a temporary probe folder.

Current code: not currently used.

Persistence evidence: `mail:imap_ro` created a unique `OpenClaw-GH38-persist-*`
folder; after logout and a new IMAP connection, `LIST` showed the folder. The
probe then deleted the folder and verified it was gone.

### `mail.imap.delete`

User story: delete a mailbox folder.

Examples:

- Remove a temporary probe folder.
- Remove an obsolete automation folder.

Current code: not currently used.

### `mail.imap.rename`

User story: rename or move a mailbox folder in the folder hierarchy.

Examples:

- Rename an automation folder.
- Move a folder under an archive namespace.

Current code: not currently used.

### `mail.imap.subscribe`

User story: mark a mailbox as subscribed.

Examples:

- Make a folder appear in subscribed-folder views.
- Configure which folders a user-facing mail client should show.

Current code: not currently used.

### `mail.imap.unsubscribe`

User story: remove a mailbox from the subscribed-folder set.

Examples:

- Hide a folder from subscribed-folder views.
- Undo a prior `SUBSCRIBE`.

Current code: not currently used.

### `mail.imap.append`

User story: add a message to a mailbox.

Examples:

- Save an outbound copy.
- Import an `.eml` file into a mailbox.
- Create a synthetic probe message.

Current code: not currently used.

### `mail.imap.store`

User story: mutate message flags by sequence id.

Examples:

- Mark as read with `\Seen`.
- Mark as deleted with `\Deleted`.
- Add or remove flags used by a workflow.

Current code: not currently used.

Design note: this is the operation that made the `mail:imap_ro` behavior
important. With read-write `SELECT`, Yandex accepted destructive flag mutation
with `mail:imap_ro`; with read-only selection, Yandex rejected it.

### `mail.imap.copy`

User story: copy a message into another mailbox.

Examples:

- Archive a message without removing it from `INBOX`.
- Copy a message to a processing folder.

Current code: not currently used.

### `mail.imap.expunge`

User story: permanently remove messages already marked `\Deleted` in the
selected mailbox.

Examples:

- Complete a delete workflow after `STORE +FLAGS \Deleted`.
- Clean up a temporary probe mailbox.

Current code: not currently used.

Design note: `EXPUNGE` is only destructive if messages are already marked
`\Deleted` in the selected mailbox.

### `mail.imap.uid.store`

User story: mutate message flags by stable UID.

Examples:

- Mark a specific UID as read or deleted.
- Apply workflow flags without relying on sequence numbers.

Current code: not currently used.

### `mail.imap.uid.copy`

User story: copy a specific UID into another mailbox.

Examples:

- Archive a specific fetched message.
- Copy a message into a downstream processing folder.

Current code: not currently used.

### `mail.imap.uid.delete_matching.live_realty`

User story: live verification that a matching real message can or cannot be
deleted under the current runtime guardrail.

This is a probe-only method, not a product feature.

Scenario:

- Search `INBOX` for `FROM "{imap_delete_probe_sender}"`.
- Take one matching UID.
- Attempt `UID STORE +FLAGS.SILENT (\Deleted)`.
- Attempt `EXPUNGE` only if the delete flag step succeeds.
- Verify whether the target UID remains.

Current code: not currently used.

Design note: this method exists to prove the runtime guardrail. With
`mail:imap_ro` and forced read-only mailbox selection, Yandex rejects the flag
mutation with "Can not store in read-only folder".

## Scenario Summary

Readonly scenarios:

- Fetch incoming mail for downstream skills.
- Search mail by sender, subject, date, UID, or configured filter.
- Download headers, full messages, and attachments.
- Inspect mailbox folder lists and mailbox counters.
- Maintain and close read-only sessions.

Readwrite scenarios:

- Create, delete, rename, subscribe, or unsubscribe folders.
- Append/import messages.
- Mark messages read, deleted, or otherwise flagged.
- Copy messages between folders.
- Permanently remove messages via `EXPUNGE` or read-write `CLOSE` after
  `\Deleted` flags exist.

Runtime implication:

- Current yandex-office mail-fetch scenarios belong in the readonly group.
- Any future scenario that archives, flags, deletes, imports, moves, or
  reorganizes mail must be implemented as readwrite and require `mail:imap_full`.
