#!/usr/bin/env python3
"""Locally migrate one managed token file to app-name-number keys.

Dry-run by default. No provider calls, token verification, or secret output.
Writes use a same-directory private staging file and atomic replacement.
"""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.auth import app_keyed_tokens, load_token_file
from common.config import AUTH_PATH, _deep_merge, load_global_config, load_agent_config_payload, resolve_data_dir


def migrate(path, config, *, apply=False):
    old = load_token_file(path)
    new = app_keyed_tokens(old, config)
    changed = new != old
    if changed and apply:
        staging = path.with_name(path.name + '.migrating')
        fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as out:
                json.dump(new, out, ensure_ascii=False, indent=2)
                out.write('\n')
                out.flush()
                os.fsync(out.fileno())
            if load_token_file(path) != old:
                raise RuntimeError('Token file changed concurrently; migration not applied')
            os.replace(staging, path)
        finally:
            if staging.exists():
                staging.unlink()
    return {'changed': changed, 'applied': bool(changed and apply), 'entries': len(new) - int('email' in new)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account', required=True)
    parser.add_argument('--data-dir')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        if not args.account or Path(args.account).name != args.account or args.account in {'.', '..'}:
            raise ValueError('Invalid account name')
        _, global_config = load_global_config(Path(__file__).resolve().parents[1])
        _, agent_config = load_agent_config_payload(resolve_data_dir(data_dir_override=args.data_dir))
        config = _deep_merge(global_config, agent_config)
        path = AUTH_PATH.expanduser() / (args.account + '.token')
        print(json.dumps(migrate(path, config, apply=args.apply)))
    except Exception as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': 'Migration failed; inspect catalog mapping or file permissions. Secret values omitted.'}))
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
