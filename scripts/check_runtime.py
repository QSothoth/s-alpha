#!/usr/bin/env python3
"""Check the project interpreter and locked dependencies before scheduled work."""
import argparse
import importlib
from importlib import metadata
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def check(publisher=False):
    if Path(sys.prefix).resolve() != (ROOT / '.venv').resolve():
        raise RuntimeError(f'use {ROOT}/.venv/bin/python; active prefix: {sys.prefix}')
    for line in (ROOT / 'requirements.lock').read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        name, expected = line.split('==')
        actual = metadata.version(name)
        if actual != expected:
            raise RuntimeError(f'{name}: expected {expected}, installed {actual}; restore requirements.lock')
    for name in ('numpy', 'pandas', 'futu'):
        importlib.import_module(name)
    if publisher:
        for path in ('/usr/bin/chromium', '/usr/bin/tencent-channel-cli'):
            if not os.access(path, os.X_OK):
                raise RuntimeError(f'missing executable: {path}')
        sys.path.insert(0, str(ROOT))
        importlib.import_module('research.trader_board_cards')
    print(f'runtime OK: {sys.executable}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publisher', action='store_true')
    args = parser.parse_args()
    try:
        check(args.publisher)
    except (RuntimeError, ImportError, OSError) as exc:
        print(f'runtime check failed: {exc}', file=sys.stderr)
        sys.exit(1)
