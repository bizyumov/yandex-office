---
name: yandex-disk
description: >
  Download files from Yandex Disk by public share links (yadi.sk). Retrieves
  file metadata and download URLs via Yandex Disk REST API. Use when downloading
  shared files from Yandex Disk, fetching meeting recordings, or working with
  yadi.sk links.
license: MIT
compatibility: Requires Python 3.10+, requests, network access to Yandex Disk API
metadata:
  author: bizyumov
  version: "1.0"
---

# Yandex Disk

Download public files from Yandex Disk using share links.

## Quick Start

```bash
python scripts/download.py "https://yadi.sk/d/x4dG3ImjPMSvzg" --output ./downloads/
```

## Python API

```python
from scripts.download import YandexDisk

disk = YandexDisk()
meta = disk.get_public_meta("https://yadi.sk/d/x4dG3ImjPMSvzg")
print(f"File: {meta['name']}, Size: {meta['size']} bytes")

disk.download("https://yadi.sk/d/x4dG3ImjPMSvzg", output_dir="./downloads/")
```

## Authentication

For public files: no token required.

For private files or higher rate limits, set a Yandex Disk OAuth token:

```bash
export YANDEX_DISK_TOKEN="your_oauth_token"
```

Generate a token with `yandex-mail/scripts/oauth_setup.py --service disk --scopes disk:read`.

## API Reference

- [Yandex Disk API quickstart](https://yandex.ru/dev/disk-api/doc/ru/concepts/quickstart)
- [API playground](https://yandex.ru/dev/disk/poligon/)

See [references/api.md](references/api.md) for endpoint details.
