#!/usr/bin/env python3
"""
Export form responses from Yandex Forms API.
Supports XLSX and JSON export formats.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

FORMS_API = "https://api.forms.yandex.net/v1"

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.auth import resolve_token
from common.config import load_runtime_context


def start_export(form_id: str, token: str, fmt: str = "xlsx") -> Optional[str]:
    """
    Start async export operation.
    Returns operation_id if successful.
    """
    url = f"{FORMS_API}/surveys/{form_id}/answers/export"
    headers = {"Authorization": f"OAuth {token}"}
    params = {"format": fmt}
    
    response = requests.post(url, json=params, headers=headers)
    
    if response.status_code == 202:
        result = response.json()
        return result.get("id")
    elif response.status_code == 401:
        raise PermissionError("Invalid or expired OAuth token")
    elif response.status_code == 403:
        raise PermissionError(f"No access to form {form_id}")
    elif response.status_code == 404:
        raise FileNotFoundError(f"Form {form_id} not found")
    else:
        raise RuntimeError(f"Export failed: {response.status_code} - {response.text}")


def check_operation(operation_id: str, token: str) -> bool:
    """Check if export operation is complete."""
    url = f"{FORMS_API}/operations/{operation_id}"
    headers = {"Authorization": f"OAuth {token}"}
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        result = response.json()
        return result.get("status") == "ok"
    elif response.status_code == 404:
        raise FileNotFoundError(f"Operation {operation_id} not found")
    else:
        raise RuntimeError(f"Operation check failed: {response.status_code}")


def download_result(form_id: str, operation_id: str, token: str) -> bytes:
    """Download exported file content."""
    url = f"{FORMS_API}/surveys/{form_id}/answers/export-results"
    headers = {"Authorization": f"OAuth {token}"}
    params = {"task_id": operation_id}
    
    response = requests.get(url, params=params, headers=headers)
    
    if response.status_code == 200:
        return response.content
    elif response.status_code == 404:
        raise FileNotFoundError("Export result not ready or not found")
    else:
        raise RuntimeError(f"Download failed: {response.status_code}")


def save_export(
    form_id: str,
    account: str,
    content: bytes,
    output_dir: Path,
    fmt: str,
    operation_id: str
) -> dict:
    """Save exported file and metadata."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
    
    # Create form directory
    form_dir = output_dir / "forms" / form_id
    form_dir.mkdir(parents=True, exist_ok=True)
    
    # Determine file extension
    ext = "xlsx" if fmt == "xlsx" else "json"
    filename = f"responses_{timestamp}.{ext}"
    filepath = form_dir / filename
    
    # Write file
    with open(filepath, "wb") as f:
        f.write(content)
    
    # Write metadata
    meta = {
        "form_id": form_id,
        "account": account,
        "export_format": fmt,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "operation_id": operation_id,
        "filename": filename,
        "filepath": str(filepath.relative_to(output_dir)),
        "file_size_bytes": len(content)
    }
    
    meta_path = form_dir / "meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    
    return meta


def export_form_responses(
    form_id: str,
    account: str,
    output_dir: Optional[Path] = None,
    fmt: str = "xlsx",
    poll_interval: int = 5,
    max_wait: int = 300,
    config: Optional[dict] = None
) -> dict:
    """
    Export form responses and save to disk.
    
    Args:
        form_id: Yandex Forms survey ID
        account: Account name from config
        output_dir: Output directory (default: from config)
        fmt: Export format (xlsx or json)
        poll_interval: Seconds between operation status checks
        max_wait: Maximum seconds to wait for export
        config: Optional pre-loaded config
    
    Returns:
        Dict with export metadata
    """
    runtime = load_runtime_context(__file__)
    runtime_config = config or runtime.config
    data_dir = output_dir or runtime.data_dir
    token = resolve_token(
        account=account,
        skill="forms",
        data_dir=runtime.data_dir,
        config=runtime_config,
        required_scopes=["forms:read"],
    ).token
    
    # Start export
    operation_id = start_export(form_id, token, fmt)
    print(f"Started export operation: {operation_id}", file=sys.stderr)
    
    # Poll for completion
    waited = 0
    while waited < max_wait:
        time.sleep(poll_interval)
        waited += poll_interval
        
        if check_operation(operation_id, token):
            print(f"Export completed in {waited}s", file=sys.stderr)
            break
        
        print(f"... waiting ({waited}s)", file=sys.stderr)
    else:
        raise TimeoutError(f"Export timed out after {max_wait}s")
    
    # Download result
    content = download_result(form_id, operation_id, token)
    print(f"Downloaded {len(content)} bytes", file=sys.stderr)
    
    # Save to disk
    meta = save_export(form_id, account, content, data_dir, fmt, operation_id)
    
    return meta


def main():
    parser = argparse.ArgumentParser(
        description="Export form responses from Yandex Forms"
    )
    parser.add_argument(
        "--form-id",
        required=True,
        help="Form ID (e.g., 6800cd9202848f10b272a9cc)"
    )
    parser.add_argument(
        "--account",
        required=True,
        help="Account name (e.g., ctiis)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output directory (default: from config)"
    )
    parser.add_argument(
        "--format",
        choices=["xlsx", "json"],
        default="xlsx",
        help="Export format (default: xlsx)"
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=5,
        help="Poll interval in seconds (default: 5)"
    )
    parser.add_argument(
        "--max-wait",
        type=int,
        default=300,
        help="Maximum wait time in seconds (default: 300)"
    )
    
    args = parser.parse_args()
    
    try:
        result = export_form_responses(
            form_id=args.form_id,
            account=args.account,
            output_dir=args.output,
            fmt=args.format,
            poll_interval=args.wait,
            max_wait=args.max_wait
        )
        
        # Output result as JSON
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except PermissionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except TimeoutError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
