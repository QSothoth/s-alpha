"""Streaming frozen-dataset inventory, checksums and static path checks."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import itertools
import json
import posixpath
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _type(value):
    if not value:
        return None
    if re.fullmatch(r'\d{4}-\d\d-\d\d', value):
        return 'date'
    if re.match(r'\d{4}-\d\d-\d\d[ T]', value):
        return 'datetime'
    if value in ('True', 'False', 'true', 'false'):
        return 'bool'
    try:
        int(value)
        return 'int'
    except ValueError:
        try:
            float(value)
            return 'float'
        except ValueError:
            return 'str'


def inventory(path, sample_rows=32):
    """One file at a time; types from a bounded sample, dates/symbols streamed."""
    root, files, markets, symbols = Path(path), {}, set(), set()
    first = last = None
    for p in sorted(root.rglob('*')):
        if not p.is_file() or p == root/'CHECKSUMS.sha256':
            continue
        relative = p.relative_to(root).as_posix()
        info = dict(bytes=p.stat().st_size)
        if p.name.endswith(('.csv', '.csv.gz')):
            opener = gzip.open if p.suffix == '.gz' else open
            with opener(p, 'rt', newline='', encoding='utf-8-sig') as stream:
                reader = csv.DictReader(stream)
                columns = reader.fieldnames or []
                sample = list(itertools.islice(reader, sample_rows))
                types = {}
                for col in columns:
                    kinds = {_type(r.get(col, '') or '') for r in sample}-{None}
                    types[col] = ('float' if kinds == {'int', 'float'} else
                                  next(iter(kinds)) if len(kinds) == 1 else 'str' if kinds else 'null')
                info['columns'] = types
                code_key = next((k for k in ('code', 'ticker', 'symbol', 'stock_code') if k in columns), None)
                date_key = next((k for k in ('date', 'day', 'time_key', 'time', 'trade_date') if k in columns), None)
                for row in itertools.chain(sample, reader):
                    if None in row:
                        raise ValueError('malformed CSV: '+str(p))
                    code = row.get(code_key) if code_key else None
                    if code:
                        symbols.add(code)
                        if '.' in code:
                            markets.add(code.split('.')[0].lower())
                    day = (row.get(date_key, '') or '')[:10] if date_key else ''
                    if re.fullmatch(r'\d{4}-\d\d-\d\d', day):
                        first = min(first, day) if first else day
                        last = max(last, day) if last else day
                if not code_key and re.fullmatch(r'(US|HK|SH|SZ)\..+', p.name.removesuffix('.gz').removesuffix('.csv')):
                    code = p.name.removesuffix('.gz').removesuffix('.csv')
                    symbols.add(code)
                    markets.add(code.split('.')[0].lower())
        else:
            info['sha256'] = sha(p)
        for part in p.relative_to(root).parts[:-1]:
            if part in ('us', 'hk', 'cn'):
                markets.add(part)
        files[relative] = info
    return dict(files=files, markets=sorted(markets), date_range=[first, last], symbols=len(symbols),
                type_sample_rows=sample_rows)


def _config(config):
    return json.loads(Path(config).read_text()) if isinstance(config, (str, Path)) else config


def check(config):
    cfg, errors, checked = _config(config), [], []
    root = Path(cfg.get('root', ROOT))
    section = cfg['datasets']
    for item in section['items']:
        name, path = item['name'], root/item['path']
        before = len(errors)
        if not path.is_dir():
            errors.append(name+': local path missing')
            continue
        manifest = path/'CHECKSUMS.sha256'
        if not manifest.is_file():
            errors.append(name+': CHECKSUMS.sha256 missing')
        elif sha(manifest) != item.get('checksums_sha256'):
            errors.append(name+': CHECKSUMS.sha256 SHA mismatch')
        else:
            for line in manifest.read_text().splitlines():
                if not line.strip():
                    continue
                match = re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?(.+)', line)
                if not match:
                    errors.append(name+': malformed checksum line')
                    continue
                digest, relative = match.groups()
                target = (path/relative).resolve()
                if not target.is_relative_to(path.resolve()) or not target.is_file():
                    errors.append(name+': checksum file missing or outside dataset: '+relative)
                elif sha(target) != digest.lower():
                    errors.append(name+': file SHA mismatch: '+relative)
        try:
            actual = inventory(path, item['schema'].get('type_sample_rows', 32))
            for key in ('files', 'markets', 'date_range', 'symbols'):
                if actual[key] != item['schema'][key]:
                    errors.append(name+': schema mismatch: '+key)
        except (OSError, ValueError, csv.Error, EOFError) as exc:
            errors.append(name+': schema unreadable: '+str(exc))
        checked.append(dict(name=name, ok=len(errors) == before))
    for item in section.get('evaluation', [])+section.get('artifacts', []):
        path = root/item['path']
        if not path.is_file() or sha(path) != item['sha256']:
            errors.append('evaluation/replay artifact SHA mismatch: '+item['path'])
    return dict(ok=not errors, errors=errors, datasets=checked,
                approved_by_user=section.get('approved_by_user'),
                can_start_round=not errors and bool(section.get('approved_by_user')))


def scan(config, files=None, git_diff=False):
    cfg, texts = _config(config), []
    root = Path(cfg.get('root', ROOT))
    if git_diff:
        diff = subprocess.check_output(['git', 'diff', 'HEAD', '--unified=0', '--', '*.py', '*.js'],
                                       cwd=root, text=True)
        texts.append(('git_diff', '\n'.join(s[1:] for s in diff.splitlines()
                                           if s.startswith('+') and not s.startswith('+++'))))
        extra = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'],
                                        cwd=root, text=True).split('\0')
        files = list(files or [])+[s for s in extra if s.endswith(('.py', '.js'))]
    for file in files or []:
        texts.append((str(file), (root/file).read_text()))
    allowed = {Path(item['path']).as_posix().strip('/') for item in cfg['datasets']['items']}
    caches = [item['path'].rstrip('/') for item in cfg['datasets'].get('derived_caches', [])
              if item.get('producer', '').startswith('studies.trader_data')]
    bad = []
    for name, content in texts:
        # Normalize literal paths and pathlib joins before checking boundaries.
        content = re.sub(r"['\"]data['\"]\s*/\s*['\"]([A-Za-z0-9_.-]+)['\"]", r'data/\1', content)
        while re.search(r"(data/[A-Za-z0-9_./-]+)\s*/\s*['\"]([A-Za-z0-9_.-]+)['\"]", content):
            content = re.sub(r"(data/[A-Za-z0-9_./-]+)\s*/\s*['\"]([A-Za-z0-9_.-]+)['\"]", r'\1/\2', content)
        for match in re.finditer(r'(?<![\w.-])data/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', content):
            path = posixpath.normpath(match.group().rstrip('.'))
            if not any(path == p or path.startswith(p+'/') for p in list(allowed)+caches):
                bad.append(dict(file=name, path=path))
    return dict(ok=not bad, violations=bad)


def main(argv=None):
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('command', choices=('check', 'scan'))
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--git-diff', action='store_true')
    parser.add_argument('files', nargs='*', type=Path)
    args = parser.parse_args(argv)
    result = check(args.config) if args.command == 'check' else scan(args.config, args.files, args.git_diff)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
