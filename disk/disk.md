---
name: disk
description: Disk / Диск — list, upload, download, import direct URLs, and manage publish/share settings for Yandex Disk resources. Use for public links, private disk:/ paths, app:/ paths, large-file transport, and controlled share links.
license: MIT
compatibility: Requires Python 3.10+, requests, network access to Yandex Disk API; optional boto3 for S3 transport
metadata:
  author: bizyumov
  version: "2026.6.12"
---

# Yandex Disk / Диск

Download public files from Yandex Disk, work with private `disk:/` and `app:/`
paths, upload files, import direct URLs, and manage share links.

Use `disk/scripts/disk.py` as the canonical command surface:

- `download`: public-link download/materialization and private file download
- `list`: authenticated `disk:/` and `app:/` browsing
- `upload`: direct local file upload and optional publish
- `import-url`: Disk upload-from-URL
- `share`: publish/update/info/unpublish
- `manage`: mkdir/delete/copy/move
- `s3-upload`: optional S3-mediated upload transport

The individual files under `disk/scripts/` remain thin adapters for direct
entry, but they are not the architecture. Disk business logic lives in
`disk/lib/api.py`, `disk/lib/workflows.py`, `disk/lib/s3.py`, and
`disk/lib/cli.py`.

## Quick Start

```bash
python3 <full-path-to-yandex-office>/disk/scripts/disk.py download "https://yadi.sk/d/x4dG3ImjPMSvzg" --output ./downloads/

# Materialize a public folder as files instead of downloading the provider archive
python3 <full-path-to-yandex-office>/disk/scripts/disk.py download "https://disk.yandex.ru/d/<id>" --materialize-dir --output ./downloads/

# Flatten only the public folder wrapper while preserving nested children
python3 <full-path-to-yandex-office>/disk/scripts/disk.py download "https://disk.yandex.ru/d/<id>" --flatten-single-root --output ./downloads/

# Download an authenticated private file
python3 <full-path-to-yandex-office>/disk/scripts/disk.py download "disk:/Docs/report.pdf" --account alex --output ./downloads/

# List private Disk resources
python3 <full-path-to-yandex-office>/disk/scripts/disk.py list --account alex --path "disk:/Docs" --jsonl

# Publish a Disk file for public read access
python3 <full-path-to-yandex-office>/disk/scripts/disk.py share publish --account alex --path "disk:/Docs/report.pdf" --access all --rights read

# Upload a local file and auto-create missing parent folders
python3 <full-path-to-yandex-office>/disk/scripts/disk.py upload --account alex --local ./photo.jpg --remote "disk:/Проекты/photo.jpg"

# Upload and publish in one step
python3 <full-path-to-yandex-office>/disk/scripts/disk.py upload --account alex --local ./photo.jpg --remote "disk:/Проекты/photo.jpg" --publish --access all --rights read

# Import a direct downloadable URL into Disk
python3 <full-path-to-yandex-office>/disk/scripts/disk.py import-url --account alex --source-url "https://example.com/file.bin" --remote "disk:/Imports/file.bin" --wait

# Bridge a local large file through temporary S3 object storage
python3 <full-path-to-yandex-office>/disk/scripts/disk.py s3-upload --account alex --local ./backup.tar.gz --remote "disk:/Backups/backup.tar.gz"

# Inspect current share settings
python3 <full-path-to-yandex-office>/disk/scripts/disk.py share info --account alex --path "disk:/Docs/report.pdf"

# Revoke access
python3 <full-path-to-yandex-office>/disk/scripts/disk.py share unpublish --account alex --path "disk:/Docs/report.pdf"

# Manage files without changing share settings
python3 <full-path-to-yandex-office>/disk/scripts/disk.py manage mkdir --account alex --path "app:/Reports"
```

## Python API

```python
from disk.lib.workflows import YandexDisk

disk = YandexDisk()
meta = disk.get_public_meta("https://yadi.sk/d/x4dG3ImjPMSvzg")
print(f"File: {meta['name']}, Size: {meta['size']} bytes")

public_download = disk.download_with_meta(
    "https://yadi.sk/d/x4dG3ImjPMSvzg",
    output_dir="./downloads/",
)
print(public_download["path"])

private_file = disk.download_private_file(
    "disk:/Docs/report.pdf",
    output_dir="./downloads/",
)
print(private_file["path"])

items = disk.list_tree("app:/Reports", recursive=True)
print(len(items))

share = disk.publish_file(
    path="disk:/Docs/report.pdf",
    access="all",
    rights="read",
)
print(share["public_url"])

upload = disk.upload_and_publish(
    "./photo.jpg",
    "disk:/Проекты/photo.jpg",
    access="all",
    rights="read",
)
print(upload["public_url"])

imported = disk.upload_from_url(
    source_url="https://example.com/file.bin",
    remote_path="disk:/Imports/file.bin",
    overwrite=True,
    wait=True,
)
print(imported["operation_status"])

disk.ensure_dir("app:/Reports")
disk.copy_resource("app:/Reports/source.txt", "app:/Reports/copy.txt")
disk.move_resource("app:/Reports/copy.txt", "app:/Reports/final.txt")
disk.delete_resource("app:/Reports/final.txt", permanently=True)
```

`disk.lib.client` remains as a small compatibility import facade for older
callers; new code should import provider plumbing from `disk.lib.api` and
business workflows from `disk.lib.workflows`.

## Authentication

For public files: no token required.

For private files, uploads, or any share-management operation, use managed auth
authorized through `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py`. Raw-token environment fallbacks are not
supported runtime auth paths.

If multiple managed accounts exist, pass `--account` so runtime selects the
intended account. Pass `--data-dir` when running outside the CWD whose
`./yandex-data` should be used.

`disk:/` paths and `app:/` paths are different provider namespaces:

- `disk:/...` addresses the visible user Disk and uses methods such as
  `disk.resources.get.disk`; reads require `cloud_api:disk.read`, writes require
  `cloud_api:disk.write`, and copy/move across existing Disk files require both
  read and write.
- `app:/...` addresses the app folder and uses matching `*.app_folder` method
  ids; `cloud_api:disk.app_folder` covers practical read/write CRUD in that
  namespace.
- Public links use `/v1/disk/public/resources*` and do not prove private
  `disk:/` or `app:/` access.

Download-only app:
- `cloud_api:disk.read`

App-folder-only app:
- `cloud_api:disk.app_folder`

Full Disk app:
- `cloud_api:disk.read`
- `cloud_api:disk.write`
- `cloud_api:disk.app_folder`

Using the full path to the shared Yandex skill, authorize a download-capable app token:

```bash
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py \
  --email user@yandex.ru \
  --account alex \
  --app disk-read
```

Authorize an upload/share-management app token:

```bash
python3 <full-path-to-yandex-office>/scripts/oauth_setup.py \
  --email user@yandex.ru \
  --account alex \
  --app disk-full
```

Recommended: use `--app disk-read` for read/download. Use `--app disk-full`
only when the user explicitly approves upload/share-management permissions. If
the workflow is restricted to `app:/`, use `--app disk-app`. If the app's scopes
change later, refresh authorization through `yandex-office`.

## Important: Telemost Recordings

Telemost recording links may look public (`yadi.sk/d/...`) but can still be
organization-restricted by Yandex.

Behavior to expect:

- Public-link Disk API calls are tokenless and can return `404` for
  organization-restricted recordings.
- `HEAD` requests are not a reliable availability check.

CLI notes:

- Use `--account` for non-public Disk operations. If omitted, the central auth
  dispatcher may infer the account only when exactly one account alias is
  available.
- Use `--verbose` to see endpoint calls.

## Share Management

`disk/scripts/disk.py share` is share-only:

- `publish`
- `update`
- `info`
- `unpublish`

`disk/scripts/disk.py manage` owns file-management operations:

- `mkdir`
- `copy`
- `move`
- `delete`

### Share options

| Option | Meaning |
|---|---|
| `--access` | `all` creates a public link; `employees` creates an organization-only link when used with the documented publish payload |
| `--org-id` | Organization ID for `--access employees`; optional only when runtime already knows the organization for the selected account |
| `--rights` | `read`, `write`, `read_without_download`, `read_with_password`, `read_with_password_without_download` |
| `--password` | Required for password-protected rights |
| `--available-until` | TTL in seconds; future Unix timestamps are also accepted for compatibility. Omit or pass `null` for infinite sharing |
| `--user-ids` | Per-user access overrides |
| `--group-ids` | Per-group access overrides |
| `--department-ids` | Per-department access overrides |

### How To Obtain `org_id`

Reliable method:

1. Use a selected account alias whose authorized app covers `directory:read_organization`.
2. Query organization data through `yandex-office` managed auth.
3. Read `organizations[].id` from the response.
4. Pass that value with `--org-id` for organization-restricted publishing.

Do not extract bearer tokens or call this API with raw `Authorization` headers
from agent code; token storage and use stay inside `yandex-office`.

Notes:

- This works only if the selected account alias has managed auth linked to an app covering the required scope and that Yandex account can view organization data. In practice, that means an admin path.
- Non-admin Yandex accounts may get `403` and should not be expected to auto-discover `org_id`.
- If runtime already knows `org_id` for the selected account, Disk publishing
  does not need `--org-id`.

### Associate Org ID With Domain Name

Operationally, the safe association rule is:

1. discover `org_id` via `GET /directory/v1/org` using managed auth for an admin-capable account alias;
2. fetch organization users via `GET /directory/v1/org/{orgId}/users`;
3. derive the organization's corporate email domains from user emails and cache the mapping.

Example:

- `<org_id> -> example.com`

This is a practical deployment mapping, not a claim that the `Organizations` response itself contains domain names. If you need an authoritative domain inventory, that belongs in the `directory` sub-skill and should be fetched/cached there.

### Examples

Public share:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/disk.py share publish \
  --account alex \
  --path "disk:/Docs/report.pdf" \
  --access all \
  --rights read
```

Organization-only share:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/disk.py share publish \
  --account mary \
  --path "disk:/Docs/report.pdf" \
  --access employees \
  --rights read
```

Live-verified on March 11, 2026:
- the resulting `public_url` is not anonymously resolvable through `/v1/disk/public/resources`
- organization-only resources must be accessed through authenticated resource APIs by path, not by `/v1/disk/public/resources?public_key=...`

Password-protected share:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/disk.py share publish \
  --account alex \
  --path "disk:/Docs/report.pdf" \
  --access all \
  --rights read_with_password \
  --password "secret-pass"
```

Expiring public share:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/disk.py share update \
  --account alex \
  --path "disk:/Docs/report.pdf" \
  --access all \
  --rights write \
  --available-until 86400
```

`--available-until` now accepts the intended TTL-in-seconds interface and converts it to the API's expiry timestamp. Future Unix timestamps are still accepted for compatibility. Omitting the option, or passing `null` through the Python API, produces infinite sharing.

## Upload Workflow

`disk/scripts/disk.py upload` uploads one local file to a `disk:/` or `app:/` path.

Behavior:

- parent directories are created automatically by default
- overwrite is disabled by default
- `--publish` reuses the same share options as `disk/scripts/disk.py share`
- published uploads include an `attachment` object with `{fileName, url, size}`
  for Calendar attachment handoff consumers
- Unicode remote paths such as `disk:/Проекты/photo.jpg` work directly; do not pre-encode them

The separate `public_calendar/v1/disk` upload APIs are not implemented here;
managed OAuth probes returned 403 for available accounts. The supported Disk
boundary for attachment consumers is standard upload, publish, and the
structured `{fileName, url, size}` handoff.

### Upload-only examples

Upload into a new nested folder:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/disk.py upload \
  --account alex \
  --local ./build/report.pdf \
  --remote "disk:/Projects/2026/report.pdf"
```

Upload with overwrite:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/disk.py upload \
  --account alex \
  --local ./build/report.pdf \
  --remote "disk:/Projects/2026/report.pdf" \
  --overwrite
```

Disable parent auto-creation:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/disk.py upload \
  --account alex \
  --local ./build/report.pdf \
  --remote "disk:/Projects/2026/report.pdf" \
  --no-create-parents
```

### Upload and publish examples

Upload and immediately publish a public read link:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/disk.py upload \
  --account alex \
  --local ./photo.jpg \
  --remote "disk:/Проекты/photo.jpg" \
  --publish \
  --access all \
  --rights read
```

Upload and attempt an org-only link:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/disk.py upload \
  --account mary \
  --local ./report.pdf \
  --remote "disk:/Проекты/Какой-то проект на русском/report.pdf" \
  --publish \
  --access employees \
  --rights read
```

This flow is live-verified with the documented request shape:
- query params: `path=...`, `allow_address_access=true`
- JSON body uses `public_settings.accesses[].macros`

Inspect current share settings after upload:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/disk.py share info --account alex --path "disk:/Проекты/photo.jpg"
```

## Listing And Private Downloads

Use `disk/scripts/disk.py list` for authenticated `disk:/` and `app:/` browsing.
Non-recursive mode honors `--limit` and `--offset`; `--recursive` walks child
folders and emits normalized metadata. `--jsonl` prints one resource per line.

Use `disk/scripts/disk.py download` with a private path to download one authenticated
file. Use `--manifest` and `--source-root` to materialize a selected set of
private files while preserving their paths relative to the source root:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/disk.py download \
  --account alex \
  --manifest ./selected.jsonl \
  --source-root "disk:/Projects" \
  --output ./selected-files
```

The manifest is a JSON array or JSONL stream with `path` entries. Entries must
stay under `--source-root`; absolute local paths and `..` traversal are rejected.

## Public Folder Materialization

Public file links accept `--materialize-dir` and `--flatten-single-root` as
tolerated no-ops and report `folder_mode_applied: false`.

Public folder links support two file materialization modes:

- `--materialize-dir` preserves the public folder wrapper under the output dir.
- `--flatten-single-root` implies materialization and omits only that one public
  folder wrapper; nested child directories are preserved.

The old provider archive download remains the default when neither flag is
present.

## URL Import

`disk/scripts/disk.py import-url` calls `POST /v1/disk/resources/upload` with a
source URL and waits for the Disk operation when `--wait` is present. It prints
only the source host and a redaction marker, not the full source URL. The
destination parent folder must already exist; use `disk/scripts/disk.py manage mkdir`
first when importing into a new folder.

Use this for direct downloadable object URLs. A Disk public share page URL is
not the same thing as a direct object URL: live verification showed that
upload-from-URL against a public share page succeeds but imports the HTML share
page, not the shared file bytes.

## S3 Transport

`disk/scripts/disk.py s3-upload` is optional and imports `boto3` only when invoked.
It uploads the local file to S3-compatible Object Storage, verifies object size
with `head_object`, creates a presigned GET URL in memory, asks Disk to import
that URL, waits for the operation, verifies final Disk metadata size, and
deletes temporary S3 objects unless `--keep-s3` is passed.
Multipart threshold, chunk size, and transfer concurrency are configurable with
`--multipart-threshold-mib`, `--multipart-chunk-mib`, and `--max-concurrency`.
When provider hash metadata is absent, the JSON report uses `"hash": null` and
`"hash_status": "not_provided"`.

The helper reads non-secret settings from `disk.s3`:
`disk.s3.endpoint_url`, `disk.s3.region`, `disk.s3.bucket`, `disk.s3.prefix`,
`disk.s3.presign_ttl_seconds`, `disk.s3.cleanup_after_disk_import`,
`disk.s3.multipart_threshold_mib`, `disk.s3.multipart_chunk_mib`, and
`disk.s3.max_concurrency`. CLI options with the same meaning override those
settings for one run. The default bucket is `yandex-office`; live verification
can pass a deployment bucket explicitly. S3 credentials are supplied to the
boto3 runtime by the operator's environment or credential configuration; the
skill does not parse credential files or accept S3 secret values on the command
line.

The S3 helper creates missing Disk parent folders before URL import by default,
matching direct upload behavior. Pass `--no-create-parents` when the destination
parent must already exist.

## Performance Notes

Live measured on June 12, 2026 with account `personal` for `disk:/` and account
`bdi` for `app:/`:

- primary archive fixture `gitea-20260611T010009Z.tar.gz`
  (1,039,233,346 bytes): direct `disk:/` upload via `disk.py upload` was stopped
  incomplete at 322,174,976 bytes (31.00%) after 2,237 s, averaging
  140.6 KiB/s with an 83.0 min ETA remaining; S3-mediated `disk:/` upload via
  `disk.py s3-upload` completed in 100.215 s total (9.890 MiB/s), with 85.432 s
  spent uploading to S3 and 14.524 s spent importing into Disk.
- app-folder smoke fixture `bamboo_webinar_20260318.webm`
  (17,990,832 bytes): direct `app:/` upload via `disk.py upload` took 140 s
  (0.123 MiB/s); S3-mediated `app:/` upload via `disk.py s3-upload` took 6.239 s
  total (2.750 MiB/s).

The direct upload path remains one Disk upload-link request followed by one
file-body `PUT` to the provider upload URL. S3 is a transport option, not a
replacement for normal direct uploads.

## Live Verification Matrix

Live-verified on March 11, 2026 against a real Yandex 360 organization:

- `access=employees`, `rights=read`: works
- `user_ids=[...]`, `rights=read`: works
- `group_ids=[...]`, `rights=read`: works
- `department_ids=[...]`, `rights=read`: works
- `access=employees`, `rights=read_with_password`, `password=...`: works
- `access=all`, `rights=read_with_password`, `password=...`: works

Observed verification rule:

- organization-only links still receive a `public_url`
- anonymous `GET /v1/disk/public/resources*` returns `404`
- authenticated access for organization-only resources should use `/v1/disk/resources?path=disk:/...` or other selected-account/org-authorized resource APIs when the path is known

Operational rule for link access:

- if managed auth is available for the selected account alias, the disk client uses it by default even for public-looking links
- anonymous access is opt-in only, for explicit anonymous-access checks (`--anonymous`) or test scenarios
- `/v1/disk/public/resources*` should be treated as public-share infrastructure, not as the canonical retrieval API for organization-only shares

Known limitation:

- `disk.py share info` / `get_share_info()` can reliably return `public_key` and `public_url`
- Yandex resource metadata did not echo the configured `accesses` array back in live tests, so `public_settings` often comes back as `{}` even for working restricted links and the client does not synthesize missing ACLs

## API Reference

- [Yandex Disk API quickstart](https://yandex.ru/dev/disk-api/doc/ru/concepts/quickstart)
- [API playground](https://yandex.ru/dev/disk/poligon/)

See [references/api.md](references/api.md) for endpoint details.
