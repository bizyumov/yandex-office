#!/usr/bin/env python3
"""
Yandex Disk public file downloader.

Downloads files from Yandex Disk using public share links (yadi.sk).
Uses the Yandex Disk REST API v1.

API docs: https://yandex.ru/dev/disk-api/doc/ru/concepts/quickstart
Playground: https://yandex.ru/dev/disk/poligon/

Usage:
    python download.py "https://yadi.sk/d/abc123" --output ./downloads/
    python download.py "https://disk.yandex.ru/d/abc123" --output ./downloads/
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from urllib.parse import urlparse, urlencode

try:
    import requests
except ImportError:
    print("Missing dependency: pip install requests", file=sys.stderr)
    sys.exit(1)


logger = logging.getLogger("YandexDisk")

API_BASE = "https://cloud-api.yandex.net"


class YandexDisk:
    """Client for Yandex Disk REST API (public resources)."""

    def __init__(self, token: str | None = None):
        self.token = token or os.getenv("YANDEX_DISK_TOKEN")
        self.session = requests.Session()
        if self.token:
            self.session.headers["Authorization"] = f"OAuth {self.token}"

    def get_public_meta(self, public_url: str) -> dict:
        """Get metadata for a public file or directory.

        GET /v1/disk/public/resources?public_key={url}

        Returns dict with: name, size, mime_type, created, modified, public_url, etc.
        """
        resp = self.session.get(
            f"{API_BASE}/v1/disk/public/resources",
            params={"public_key": public_url},
        )
        resp.raise_for_status()
        data = resp.json()

        return {
            "name": data.get("name", ""),
            "size": data.get("size", 0),
            "mime_type": data.get("mime_type", ""),
            "created": data.get("created", ""),
            "modified": data.get("modified", ""),
            "public_url": data.get("public_url", public_url),
            "type": data.get("type", "file"),
            "path": data.get("path", ""),
        }

    def get_download_link(self, public_url: str, path: str = "") -> str:
        """Get direct download URL for a public resource.

        GET /v1/disk/public/resources/download?public_key={url}

        For directories, pass path= to specify the file within.
        Returns the direct download href.
        """
        params = {"public_key": public_url}
        if path:
            params["path"] = path

        resp = self.session.get(
            f"{API_BASE}/v1/disk/public/resources/download",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()["href"]

    def download(
        self,
        public_url: str,
        output_dir: str = ".",
        filename: str | None = None,
        path: str = "",
    ) -> Path:
        """Download a public file to local disk.

        Args:
            public_url: yadi.sk or disk.yandex.ru share link
            output_dir: directory to save into
            filename: override output filename (default: use original name)
            path: for directories, the file path within

        Returns:
            Path to the downloaded file.
        """
        # Get metadata for filename
        if not filename:
            meta = self.get_public_meta(public_url)
            filename = meta["name"] or "download"

        # Get direct download link
        href = self.get_download_link(public_url, path=path)

        # Download
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        filepath = out_path / filename

        logger.info(f"Downloading {filename} to {filepath}")

        resp = self.session.get(href, stream=True)
        resp.raise_for_status()

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        size = filepath.stat().st_size
        logger.info(f"Downloaded {size} bytes to {filepath}")

        return filepath

    def download_with_meta(
        self,
        public_url: str,
        output_dir: str = ".",
        filename: str | None = None,
    ) -> dict:
        """Download file and return metadata dict.

        Convenience method for use by other skills (e.g. yandex-telemost).

        Returns:
            dict with: filepath, name, size, mime_type, public_url
        """
        meta = self.get_public_meta(public_url)

        if not filename:
            filename = meta["name"] or "download"

        filepath = self.download(
            public_url, output_dir=output_dir, filename=filename
        )

        return {
            "filepath": str(filepath),
            "name": meta["name"],
            "size": filepath.stat().st_size,
            "mime_type": meta["mime_type"],
            "public_url": public_url,
        }


def main():
    parser = argparse.ArgumentParser(
        description="Download files from Yandex Disk public links",
    )
    parser.add_argument("url", help="Public yadi.sk or disk.yandex.ru link")
    parser.add_argument(
        "--output", "-o", default=".", help="Output directory (default: current)"
    )
    parser.add_argument(
        "--filename", "-f", help="Override output filename"
    )
    parser.add_argument(
        "--meta", action="store_true", help="Print file metadata as JSON"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    disk = YandexDisk()

    if args.meta:
        meta = disk.get_public_meta(args.url)
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return

    result = disk.download_with_meta(
        args.url, output_dir=args.output, filename=args.filename
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
