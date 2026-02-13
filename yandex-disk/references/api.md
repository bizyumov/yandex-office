# Yandex Disk API Reference

## Public Resources

### Get metadata

```
GET https://cloud-api.yandex.net/v1/disk/public/resources?public_key={url}
```

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

## Authentication

- **Public files:** No authentication needed.
- **Private files:** `Authorization: OAuth {token}` header.

### Token scopes

| Scope | Description |
|-------|-------------|
| `disk:read` | Read access to user's disk |
| `disk:write` | Write access to user's disk |
| `disk:app_folder` | Access to app-specific folder only |

## Rate limits

- Public API: generous limits for reasonable usage
- Authenticated: higher limits per token

## Documentation

- **Quickstart:** https://yandex.ru/dev/disk-api/doc/ru/concepts/quickstart
- **Playground:** https://yandex.ru/dev/disk/poligon/
- **App registration:** https://yandex.ru/dev/id/doc/ru/register-api
