---
name: disk
description: Disk / Диск — download files from Yandex Disk by public share links, upload files to Disk, and manage publish/share settings for Disk resources. Use when downloading shared files, fetching meeting recordings, uploading artifacts, or creating and revoking controlled share links.
license: MIT
compatibility: Requires Python 3.10+, requests, network access to Yandex Disk API
metadata:
  author: bizyumov
  version: "2026.05.19"
---

# Yandex Disk / Диск

Download public files from Yandex Disk, upload files to Disk, and manage share links.

## Quick Start

```bash
python3 <full-path-to-yandex-office>/disk/scripts/download.py "https://yadi.sk/d/x4dG3ImjPMSvzg" --output ./downloads/

# Publish a Disk file for public read access
python3 <full-path-to-yandex-office>/disk/scripts/share.py publish --account alex --path "disk:/Docs/report.pdf" --access all --rights read

# Upload a local file and auto-create missing parent folders
python3 <full-path-to-yandex-office>/disk/scripts/upload.py --account alex --local ./photo.jpg --remote "disk:/Проекты/photo.jpg"

# Upload and publish in one step
python3 <full-path-to-yandex-office>/disk/scripts/upload.py --account alex --local ./photo.jpg --remote "disk:/Проекты/photo.jpg" --publish --access all --rights read

# Inspect current share settings
python3 <full-path-to-yandex-office>/disk/scripts/share.py info --account alex --path "disk:/Docs/report.pdf"

# Revoke access
python3 <full-path-to-yandex-office>/disk/scripts/share.py unpublish --account alex --path "disk:/Docs/report.pdf"
```

## Python API

```python
from disk.scripts.download import YandexDisk

disk = YandexDisk()
meta = disk.get_public_meta("https://yadi.sk/d/x4dG3ImjPMSvzg")
print(f"File: {meta['name']}, Size: {meta['size']} bytes")

disk.download("https://yadi.sk/d/x4dG3ImjPMSvzg", output_dir="./downloads/")

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
```

## Authentication

For public files: no token required.

For private files, uploads, or any share-management operation, use managed auth
authorized through `python3 <full-path-to-yandex-office>/scripts/oauth_setup.py`. Raw-token environment fallbacks are not
supported runtime auth paths.

If multiple managed accounts exist, pass `--account` so runtime selects the
intended account.

Download-only scopes:
- `cloud_api:disk.read`

Upload/share-management scopes:
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
the app's scopes change later, refresh authorization through `yandex-office`.

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

`disk/scripts/share.py` exposes four commands:

- `publish`
- `update`
- `info`
- `unpublish`

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
python3 <full-path-to-yandex-office>/disk/scripts/share.py publish \
  --account alex \
  --path "disk:/Docs/report.pdf" \
  --access all \
  --rights read
```

Organization-only share:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/share.py publish \
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
python3 <full-path-to-yandex-office>/disk/scripts/share.py publish \
  --account alex \
  --path "disk:/Docs/report.pdf" \
  --access all \
  --rights read_with_password \
  --password "secret-pass"
```

Expiring public share:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/share.py update \
  --account alex \
  --path "disk:/Docs/report.pdf" \
  --access all \
  --rights write \
  --available-until 86400
```

`--available-until` now accepts the intended TTL-in-seconds interface and converts it to the API's expiry timestamp. Future Unix timestamps are still accepted for compatibility. Omitting the option, or passing `null` through the Python API, produces infinite sharing.

## Upload Workflow

`disk/scripts/upload.py` uploads one local file to a Disk path.

Behavior:

- parent directories are created automatically by default
- overwrite is disabled by default
- `--publish` reuses the same share options as `disk/scripts/share.py`
- Unicode remote paths such as `disk:/Проекты/photo.jpg` work directly; do not pre-encode them

### Upload-only examples

Upload into a new nested folder:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/upload.py \
  --account alex \
  --local ./build/report.pdf \
  --remote "disk:/Projects/2026/report.pdf"
```

Upload with overwrite:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/upload.py \
  --account alex \
  --local ./build/report.pdf \
  --remote "disk:/Projects/2026/report.pdf" \
  --overwrite
```

Disable parent auto-creation:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/upload.py \
  --account alex \
  --local ./build/report.pdf \
  --remote "disk:/Projects/2026/report.pdf" \
  --no-create-parents
```

### Upload and publish examples

Upload and immediately publish a public read link:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/upload.py \
  --account alex \
  --local ./photo.jpg \
  --remote "disk:/Проекты/photo.jpg" \
  --publish \
  --access all \
  --rights read
```

Upload and attempt an org-only link:

```bash
python3 <full-path-to-yandex-office>/disk/scripts/upload.py \
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
python3 <full-path-to-yandex-office>/disk/scripts/share.py info --account alex --path "disk:/Проекты/photo.jpg"
```

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

- `share.py info` / `get_share_info()` can reliably return `public_key` and `public_url`
- Yandex resource metadata did not echo the configured `accesses` array back in live tests, so `public_settings` often comes back as `{}` even for working restricted links and the client does not synthesize missing ACLs

## API Reference

- [Yandex Disk API quickstart](https://yandex.ru/dev/disk-api/doc/ru/concepts/quickstart)
- [API playground](https://yandex.ru/dev/disk/poligon/)

See [references/api.md](references/api.md) for endpoint details.
