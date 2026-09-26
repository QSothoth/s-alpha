"""Verify and stream one frozen research dataset into a new ZIP; never publish it."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import zipfile

from custody.dataset import sha256_file, write_checksums

SOURCES = {
    'or-alpha-20260925-v1': 'or-alpha-2026-09-25-holdout-work',
    'or-context-etf-k5-2018-2026-v1': 'or-context-etf-k5-2018-2026-retry1-work',
    'or-option-history-pilot-20260918-v1': 'or-option-history-pilot-20260918-work',
}

RESEARCH_REPORTS = {
    'ds1_development': '979926fa3883a416ea915c52414d06c6b717190ec39f879233e1de8fcb3f0e81',
    'ds2_development': '458314927ad18ca9645a72799a1050d4c183f2463c171905c13a77d9a0535e0e',
    'persistence_development': 'e521355a7d4a5fddfed4e35566266b146b2dcd87d42d10d161f79579a525fb61',
    'ah1_development': '3228710a553ad47bfd91113ea7de48a7425d9e86034301403b42928ba0fc3890',
    'rg1_asset_transfer': 'a3b2c9b5ba771dfc179c17851c607c05aac28d181375e0cb17d271f107315464',
}


def research_snapshot(repo, output):
    """Preserve derived data and code fingerprints; source code belongs in Git."""
    repo, output = Path(repo).resolve(), Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError('refuse to overwrite research snapshot')
    prefix = 'studies/us_opening_range/'
    pins, archived = {}, {}

    def pin(relative, digest, *, include=True):
        path = PurePosixPath(relative)
        source = repo / relative
        if (path.is_absolute() or '..' in path.parts or '\\' in relative
                or path.as_posix() != relative or source.is_symlink()
                or not source.resolve().is_relative_to(repo)):
            raise ValueError('unsafe research source path')
        if relative in pins and pins[relative] != digest:
            raise ValueError('conflicting frozen source versions')
        if sha256_file(source) != digest:
            raise ValueError('research source checksum mismatch: ' + relative)
        pins[relative] = digest
        if include:
            archived[relative] = digest

    for name, digest in RESEARCH_REPORTS.items():
        relative = prefix + 'reports/' + name + '.json'
        pin(relative, digest)
        report = json.loads((repo / relative).read_text(encoding='utf-8'))
        artifact = [report[key] for key in ('signal_events', 'signals_artifact', 'labels_artifact') if key in report]
        if len(artifact) != 1 or not artifact[0]['path'].startswith('data/'):
            raise ValueError('one local derived artifact is required per report')
        pin(artifact[0]['path'], artifact[0]['sha256'])
        for code, expected in report['code_sha256'].items():
            pin(code, expected, include=False)
        pin(prefix + 'notes/' + report['study'] + '_PREREG.md', report['preregistration_sha256'])
    pin(prefix + 'package_data.py', sha256_file(repo / prefix / 'package_data.py'), include=False)
    # All files are approved before creating any snapshot output.
    output.mkdir(parents=True, exist_ok=False)
    for relative, digest in sorted(archived.items()):
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with (repo / relative).open('rb') as source, target.open('xb') as dest:
            shutil.copyfileobj(source, dest, 1 << 20)
        if sha256_file(target) != digest or sha256_file(repo / relative) != digest:
            raise ValueError('research source changed during snapshot: ' + relative)
    if any(sha256_file(repo / relative) != digest for relative, digest in pins.items()):
        raise ValueError('research provenance changed during snapshot')
    manifest = {
        'role': 'research/derived-signal-audit', 'created_at': datetime.now(timezone.utc).isoformat(),
        'reports': RESEARCH_REPORTS, 'original_files_sha256': pins, 'archived_files_sha256': archived,
        'note': '已暴露标签、机器报告、预登记与实现指纹快照；不含源码或原始行情，不是独立验证或完整可执行仓库。',
        'reuse': '可直接复核保存事件；重放需另取报告中固定的原行情包并使用匹配代码，不能恢复留出身份。',
        'exposure': 'RG1三ETF截至2026-09-24已用；其它九ETF分钟与全部09/25未在此快照评测。',
    }
    with (output / 'manifest.json').open('x', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
    write_checksums(output)
    return {'source': str(output), 'files': len(verified_files(output))}


def verified_files(root):
    """Require exact checksum coverage, normal relative paths and no symlinks."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('source must be a regular directory')
    files = set()
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('symlink in dataset')
        if path.is_file():
            files.add(path.relative_to(root).as_posix())
    if not {'manifest.json', 'CHECKSUMS.sha256'} <= files:
        raise ValueError('manifest and checksums are required')
    if not isinstance(json.loads((root / 'manifest.json').read_text()), dict):
        raise ValueError('manifest must be an object')
    expected = {}
    for line in (root / 'CHECKSUMS.sha256').read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        if not match:
            raise ValueError('invalid checksum line')
        digest, relative = match.groups()
        path = PurePosixPath(relative)
        if (path.is_absolute() or '..' in path.parts or '\\' in relative or
                path.as_posix() != relative or relative in expected or
                relative == 'CHECKSUMS.sha256'):
            raise ValueError('unsafe or duplicate checksum path')
        expected[relative] = digest
    if set(expected) != files - {'CHECKSUMS.sha256'}:
        raise ValueError('checksum coverage does not match dataset files')
    for relative, digest in expected.items():
        if sha256_file(root / relative) != digest:
            raise ValueError('checksum mismatch: ' + relative)
    expected['CHECKSUMS.sha256'] = sha256_file(root / 'CHECKSUMS.sha256')
    return expected


def package(root, output):
    """Preserve source bytes and directory name, with at most a 1 MiB copy buffer."""
    root, output = Path(root), Path(output)
    sidecar = output.with_name(output.name + '.sha256')
    if output.exists() or sidecar.exists():
        raise FileExistsError('refuse to overwrite archive or checksum')
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError('archive must be outside source directory')
    expected = verified_files(root)
    if any(PurePosixPath(relative).suffix in ('.py', '.pyc') for relative in expected):
        raise ValueError('Python source/bytecode belongs in Git, not data Releases')
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for relative in sorted(expected):
            digest = hashlib.sha256()
            with (root / relative).open('rb') as source, archive.open(root.name + '/' + relative, 'w') as target:
                for chunk in iter(lambda: source.read(1 << 20), b''):
                    digest.update(chunk)
                    target.write(chunk)
            if digest.hexdigest() != expected[relative]:
                raise ValueError('source changed while packaging: ' + relative)
    if verified_files(root) != expected:
        raise ValueError('source changed while packaging')
    digest = sha256_file(output)
    with sidecar.open('x', encoding='utf-8') as handle:
        handle.write(digest + '  ' + output.name + '\n')
    return {'archive': str(output), 'sha256': digest,
            'checksums_sha256': expected['CHECKSUMS.sha256'],
            'bytes': output.stat().st_size, 'files': len(expected),
            'archive_root': root.name}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--tag', choices=sorted(SOURCES))
    choice.add_argument('--research-snapshot', type=Path, metavar='NEW_DIRECTORY')
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    args = parser.parse_args(argv)
    result = (research_snapshot(args.repo_root, args.research_snapshot) if args.research_snapshot else
              package(args.data_root / SOURCES[args.tag], args.data_root / (args.tag + '.zip')))
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
