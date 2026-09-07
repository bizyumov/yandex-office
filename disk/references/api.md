# Yandex Disk API Reference

## Public Resources

These endpoints are intended for public-share infrastructure. In this repo,
public-resource calls are tokenless. Organization-only or private resources are
handled through authenticated `disk:/` or `app:/` resource paths instead.

### Get metadata

```
GET https://cloud-api.yandex.net/v1/disk/public/resources?public_key={url}
```

Use cases:

- metadata for publicly shared files
- anonymous metadata checks for public links
- browsing files inside a public shared directory with `&path=/filename.txt`

Important behavior:

- `access=all` public links work through this endpoint
- `access=employees` organization-only links return `404` here, even with an organization token
- organization-only resources should be accessed through authenticated resource APIs by path, for example `GET /v1/disk/resources?path=disk:/...`

**Response:**
```json
{
  "name": "file.mp4",
  "size": 1048576,
  "mime_type": "video/mp4",
  "type": "file",
  "created": "2026-01-15T10:30:00+00:00",
  "modified": "2026-01-15T10:30:00+00:00",
  "public_url": "https://yadi.sk/d/abc123",
  "path": "/"
}
```

### Get download link

```
GET https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key={url}
```

This follows the same rule as `/public/resources`:

- suitable for public links
- not the canonical download path for organization-only resources

**Response:**
```json
{
  "href": "https://downloader.disk.yandex.ru/...",
  "method": "GET",
  "templated": false
}
```

Then fetch the file from `href` with a standard GET request.

### For directories

Pass `&path=/filename.txt` to both endpoints to access a specific file within a shared directory.

## Managed Resources

Authenticated resources use separate capability rows for visible Disk paths and
app-folder paths. The same upstream endpoint is represented as `.disk` for
`disk:/...` and `.app_folder` for `app:/...` when OAuth behavior differs.

### Get resource metadata and listing

```
GET https://cloud-api.yandex.net/v1/disk/resources?path=disk:/Docs&limit=100&offset=0
```

Use `disk:/...` for the visible user Disk and `app:/...` for the app folder.
Directory responses include `_embedded.items`; file responses describe one
resource. `disk/scripts/disk.py list` normalizes names, paths, types, sizes,
MIME types, and stable `public_key`, `public_url`, and `public_settings` keys.

### Create directory

```
PUT https://cloud-api.yandex.net/v1/disk/resources?path=disk:/Projects/2026
```

`409 Conflict` means the directory already exists and can be treated as success for idempotent setup.

### Get upload link

```
GET https://cloud-api.yandex.net/v1/disk/resources/upload?path=disk:/Projects/2026/report.pdf&overwrite=false
```

**Response:**
```json
{
  "href": "https://uploader44klg.disk.yandex.net/upload-target",
  "method": "PUT",
  "templated": false
}
```

Upload the file body with a plain `PUT` to the returned `href`.

### Get private download link

```
GET https://cloud-api.yandex.net/v1/disk/resources/download?path=disk:/Docs/report.pdf
```

The returned `href` is a provider download URL. Treat it as sensitive runtime
material: do not store it in logs, docs, evidence, or release notes. Use the
matching `app:/...` path with the `.app_folder` capability row for app-folder
downloads.

### Upload from URL

```
POST https://cloud-api.yandex.net/v1/disk/resources/upload?path=disk:/Imports/file.bin&url=https%3A%2F%2Fexample.com%2Ffile.bin&overwrite=true&disable_redirects=false
```

Expected response is usually an operation link:

```json
{
  "href": "https://cloud-api.yandex.net/v1/disk/operations/<operation-id>",
  "method": "GET",
  "templated": false
}
```

`disk/scripts/disk.py import-url` and `disk/scripts/disk.py s3-upload` redact
the full source URL from JSON output and errors. The source must be a direct
downloadable object URL when byte identity matters. A public Disk share page URL
can be imported by the provider, but live testing showed it imports the HTML
share page rather than the shared file bytes.

The optional S3 bridge keeps non-secret S3 settings under `disk.s3` and leaves
AWS-compatible credentials to the S3 client runtime. It does not parse
credential files or accept S3 secret values on the command line.

### Poll operation

```
GET https://cloud-api.yandex.net/v1/disk/operations/<operation-id>
```

Poll until `status` is `success` or `failed`. The helper methods use this for
URL import, S3-mediated import, and asynchronous cleanup when the API returns an
operation id.

### Copy, move, and delete

```
POST https://cloud-api.yandex.net/v1/disk/resources/copy?from=disk:/Docs/a.txt&path=disk:/Docs/b.txt&overwrite=true
POST https://cloud-api.yandex.net/v1/disk/resources/move?from=disk:/Docs/b.txt&path=disk:/Docs/c.txt&overwrite=true
DELETE https://cloud-api.yandex.net/v1/disk/resources?path=disk:/Docs/c.txt&permanently=false&force_async=false
```

Source and destination must use the same surface. Do not use `disk:/` evidence
as proof of `app:/` behavior; the app-folder variants use separate decorated
method ids and `cloud_api:disk.app_folder`.

### Publish or update resource sharing

```
PUT https://cloud-api.yandex.net/v1/disk/resources/publish?path=disk:/Docs/report.pdf&allow_address_access=true
```

Expected payload shape:

```json
{
  "public_settings": {
    "available_until": 86400,
    "accesses": [
      {
        "macros": ["employees"],
        "org_id": 123456,
        "rights": ["read_without_download"]
      },
      {
        "user_ids": ["1001", "1002"],
        "rights": ["write"]
      }
    ]
  }
}
```

Observed live behavior in this repo on 2026-03-11:

- public publish (`access=all`) succeeded, but the immediate API response only returned an `href` to resource metadata
- employees-only sharing worked only after switching to the documented `public_settings.accesses[].macros` schema
- the resulting members-only link still has a `public_url`, but anonymous `/v1/disk/public/resources*` requests return `404`
- the correct authenticated retrieval path for organization-only resources is by resource path (`/v1/disk/resources?path=disk:/...`), not by `public_key`
- `user_ids`, `group_ids`, and `department_ids` behaved the same way in live tests
- the public client now accepts `available_until` as TTL seconds and converts it to the API's expiry timestamp
- omitting `available_until`, or passing `None` through the Python API, produced infinite sharing behavior

Practical implication:

- `public_url` does not mean anonymous/public access
- `/v1/disk/public/resources*` is for public-share infrastructure, not a universal access API for all share modes
- public-link APIs are tokenless public-share infrastructure
- resource metadata did not echo the configured `accesses` array back in live tests, so `get_share_info()` does not reconstruct ACLs from metadata alone

### Unpublish resource

```
PUT https://cloud-api.yandex.net/v1/disk/resources/unpublish?path=disk:/Docs/report.pdf
```

### Obtain `org_id` for organization-only sharing

Admin-capable path:

```
GET https://api360.yandex.net/directory/v1/org
Authorization: handled by managed auth in the runtime client
```

Requirements:

- scope `directory:read_organization`
- token must actually be allowed to read organization data

Operational rule:

- discover `organizations[].id`
- pass it as `org_id` for Disk publishing when organization-restricted access
  is required
- associate that `org_id` with observed corporate email domains from Directory users

## Authentication

- **Public files:** Public-resource endpoints are called without OAuth.
- **Organization-only files:** Use authenticated resource APIs by path; do not expect `/v1/disk/public/resources?public_key=...` to work.
- **Private files:** `Authorization: OAuth {token}` header through managed auth.
- **Redaction:** Do not print raw access tokens, provider download hrefs,
  presigned URLs, or unredacted source URLs.

### Token scopes

| Scope | Description |
|-------|-------------|
| `cloud_api:disk.read` | Read access to user's disk |
| `cloud_api:disk.write` | Write, upload, and share-management access |
| `cloud_api:disk.app_folder` | Access to app-specific folder used by Disk API apps |

## Rate limits

- Public API: generous limits for reasonable usage
- Authenticated: higher limits per token

## Documentation

- **Quickstart:** https://yandex.ru/dev/disk-api/doc/ru/concepts/quickstart
- **Playground:** https://yandex.ru/dev/disk/poligon/
- **App registration:** https://yandex.ru/dev/id/doc/ru/register-api
