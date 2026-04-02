# Yandex Disk API Reference

## Public Resources

These endpoints are intended for public-share infrastructure. In this repo, the client still uses OAuth by default when a token is available, even for public-looking links, because Telemost and organization-only shares can require authenticated access.

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

### Get resource metadata

```
GET https://cloud-api.yandex.net/v1/disk/resources?path=disk:/Docs/report.pdf
```

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
- when a token is available, this repo uses OAuth by default even for public-looking links
- anonymous access is opt-in only, for explicit anonymous-access checks
- resource metadata did not echo the configured `accesses` array back in live tests, so `get_share_info()` does not reconstruct ACLs from metadata alone

### Unpublish resource

```
PUT https://cloud-api.yandex.net/v1/disk/resources/unpublish?path=disk:/Docs/report.pdf
```

### Obtain `org_id` for organization-only sharing

Admin-capable path:

```
GET https://api360.yandex.net/directory/v1/org
Authorization: OAuth {token.directory}
```

Requirements:

- scope `directory:read_organization`
- token must actually be allowed to read organization data

Operational rule:

- discover `organizations[].id`
- store it as `org_id` in the account token file for reuse by Disk publishing
- associate that `org_id` with observed corporate email domains from Directory users

## Authentication

- **Public files:** Public-resource endpoints allow anonymous access, but this repo uses OAuth by default when a token is available.
- **Anonymous checks:** Use anonymous mode explicitly when you need to verify anonymous reachability.
- **Organization-only files:** Use authenticated resource APIs by path; do not expect `/v1/disk/public/resources?public_key=...` to work.
- **Private files:** `Authorization: OAuth {token}` header.

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
