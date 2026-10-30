#!/usr/bin/env python3
"""Reject sensitive paths and scan staged files, outgoing history, or release files."""
import argparse
import codecs
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile

VERSION = '8.30.1'
ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_NAMES = ('.env', '.env.*', '*.pem', '*.key', '*.p12', '*.pfx', '*.jks',
                   '*.keystore', '*.kdbx', '.git-credentials', '*.zip', '*.gz', '*.bz2', '*.xz',
                   '*.7z', '*.rar', '*.tar', '*.parquet', '*.pdf', '*.png', '*.jpg', '*.jpeg',
                   '*.gif', '*.webp', '*.ico', '*.exe', '*.dll', '*.so', '*.bin', 'id_rsa*', 'id_ed25519*', 'id_ecdsa*', 'id_dsa*',
                   '.netrc', '_netrc', '.npmrc', '.pypirc', 'credentials', 'credentials.json',
                   '*service-account*.json', '*service_account*.json')
FORBIDDEN_DIRS = {'.ssh', '.aws', '.azure', '.gnupg'}
# Committed skill-discovery symlinks: exact path -> exact target, nothing else.
ALLOWED_LINKS = {'.claude/skills': b'../skills', '.agents/skills': b'../skills'}


class GuardError(Exception):
    pass


def git(*args, output=None):
    result = subprocess.run(['git', *args], stdout=output or subprocess.PIPE,
                            stderr=subprocess.DEVNULL, check=False)
    if result.returncode:
        raise GuardError('Git inspection failed; commit or push blocked.')
    return result.stdout


def forbidden(path):
    parts = PurePosixPath(path).parts
    if any(part.lower() in FORBIDDEN_DIRS for part in parts[:-1]):
        return True
    name = parts[-1].lower()
    if name == '.env.example':
        return False
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in FORBIDDEN_NAMES)


def check_path(path):
    if forbidden(path):
        raise GuardError('Sensitive filename blocked: ' + repr(path))


def binary():
    path = Path(os.environ.get('GITLEAKS_BIN', str(
        Path.home() / '.local/share/opend-us-options/gitleaks' / VERSION / 'gitleaks')))
    try:
        result = subprocess.run([str(path), 'version'], capture_output=True, text=True)
    except OSError:
        raise GuardError('Gitleaks is missing; run python3 scripts/install_secret_guard.py.') from None
    if result.returncode or result.stdout.strip().lstrip('v') != VERSION:
        raise GuardError('Gitleaks version mismatch; reinstall the pinned scanner.')
    return str(path)


def scan(mode, target, revision=None):
    scanner = binary()
    config = ROOT / '.gitleaks.toml'
    if not config.is_file():
        raise GuardError('Gitleaks configuration is missing.')
    with tempfile.TemporaryDirectory(prefix='secret-guard-report-') as tmp:
        template = Path(tmp) / 'template'
        template.write_text('{{range .}}{{printf "%q" .File}}:{{.StartLine}} {{.RuleID}}\n{{end}}')
        report = Path(tmp) / 'report'
        command = [scanner, mode, str(target), '--config', str(config), '--redact=100',
                   '--no-banner', '--no-color', '--ignore-gitleaks-allow',
                   '--gitleaks-ignore-path', tmp, '--report-format', 'template',
                   '--report-template', str(template), '--report-path', str(report),
                   '--max-archive-depth', '3', '--max-decode-depth', '3']
        if revision:
            command.append('--log-opts=--root -m --text --no-ext-diff --no-textconv ' + revision)
        env = os.environ.copy()
        env['GOMAXPROCS'] = '2'
        env.pop('GITLEAKS_CONFIG_TOML', None)
        with open(os.devnull, 'wb') as quiet:
            result = subprocess.run(command, stdout=quiet, stderr=quiet, env=env)
        if result.returncode:
            if report.exists():
                with report.open() as stream:
                    for index, line in enumerate(stream):
                        if index == 50:
                            print('Further findings omitted.', file=sys.stderr)
                            break
                        print(line.rstrip(), file=sys.stderr)
            raise GuardError('Secret scan failed; blocked. Repair findings or scanner configuration.')


def check_text(stream, size, label):
    decoder = codecs.getincrementaldecoder('utf-8')()
    remaining = size
    first = True
    while remaining:
        chunk = stream.read(min(65536, remaining))
        if not chunk:
            raise GuardError('Truncated file inspection: ' + repr(label))
        remaining -= len(chunk)
        if b'\0' in chunk:
            raise GuardError('Binary content blocked: ' + repr(label))
        if first and (chunk.startswith((b'PK\x03\x04', b'PK\x05\x06', b'\x1f\x8b',
                                      b'BZh', b'\xfd7zXZ', b'7z\xbc\xaf', b'Rar!'))
                      or chunk[257:262] == b'ustar'):
            raise GuardError('Archive content blocked: ' + repr(label))
        first = False
        try:
            decoder.decode(chunk, final=not remaining)
        except UnicodeDecodeError:
            raise GuardError('Non-UTF-8 content blocked: ' + repr(label)) from None


def check_file(path, label):
    with Path(path).open('rb') as stream:
        check_text(stream, os.fstat(stream.fileno()).st_size, label)


def check_history_blobs(revision, legacy_oids):
    with tempfile.TemporaryFile() as errors:
        objects = subprocess.Popen(['git', 'rev-list', '--objects', '--no-object-names', revision, '--'],
                                   stdout=subprocess.PIPE, stderr=errors)
        kinds = subprocess.Popen(['git', 'cat-file', '--batch-check=%(objectname) %(objecttype)'],
                                 stdin=objects.stdout, stdout=subprocess.PIPE, stderr=errors)
        objects.stdout.close()
        blobs = subprocess.Popen(['git', 'cat-file', '--batch'], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=errors)
        try:
            for line in kinds.stdout:
                parts = line.split()
                if len(parts) != 2:
                    raise GuardError('Cannot inspect Git object type.')
                if parts[1] != b'blob':
                    continue
                blobs.stdin.write(parts[0] + b'\n')
                blobs.stdin.flush()
                header = blobs.stdout.readline().split()
                if len(header) != 3 or header[1] != b'blob':
                    raise GuardError('Cannot inspect Git blob.')
                size = int(header[2])
                if parts[0].decode() in legacy_oids:
                    while size:
                        block = blobs.stdout.read(min(size, 65536))
                        if not block:
                            raise GuardError('Truncated legacy Git blob.')
                        size -= len(block)
                else:
                    check_text(blobs.stdout, size, 'Git blob ' + parts[0].decode())
                if blobs.stdout.read(1) != b'\n':
                    raise GuardError('Invalid Git object stream.')
            blobs.stdin.close()
            if objects.wait() or kinds.wait() or blobs.wait():
                raise GuardError('Git object inspection failed.')
        finally:
            for process in (objects, kinds, blobs):
                if process.poll() is None:
                    process.kill()
                process.wait()


def staged():
    names = git('diff', '--cached', '--name-only', '--diff-filter=ACMRT', '-z').split(b'\0')
    with tempfile.TemporaryDirectory(prefix='secret-guard-index-') as tmp:
        for raw in names:
            if not raw:
                continue
            path = os.fsdecode(raw)
            check_path(path)
            entry = git('ls-files', '--stage', '--', path).split(maxsplit=3)
            if (entry and entry[0] == b'120000' and entry[2] == b'0'
                    and path in ALLOWED_LINKS and git('show', ':' + path) == ALLOWED_LINKS[path]):
                continue
            if not entry or entry[0] not in (b'100644', b'100755') or entry[2] != b'0':
                raise GuardError('Only regular, resolved files can be staged: ' + repr(path))
            destination = Path(tmp) / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('wb') as stream:
                git('show', ':' + path, output=stream)
            check_file(destination, path)
        scan('dir', tmp)


def legacy_public_blobs():
    path = ROOT / 'scripts' / 'legacy_public_blobs.json'
    if not path.exists():
        return set()
    try:
        entries = json.loads(path.read_text())
        if not isinstance(entries, list):
            raise ValueError
        pairs = set()
        for entry in entries:
            oid, name = entry['oid'], entry['path']
            if not re.fullmatch(r'[0-9a-f]{40,64}', oid) or not isinstance(name, str):
                raise ValueError
            if PurePosixPath(name).suffix.lower() not in ('.gz', '.xz', '.parquet'):
                raise ValueError
            pairs.add((oid, name))
        return pairs
    except (ValueError, TypeError, KeyError):
        raise GuardError('Invalid legacy public blob manifest; blocked.') from None


def history(revision):
    if revision != '--all' and not re.fullmatch(r'[0-9a-f]{40,64}(?:\.\.[0-9a-f]{40,64})?', revision):
        raise GuardError('History scan expects a full commit SHA or SHA..SHA.')
    legacy = legacy_public_blobs()
    command = ['git', 'log', '--format=', '--raw', '--no-abbrev', '--no-renames',
               '--diff-filter=ACMRT', '--root', '-m', '-z', revision, '--']
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
        pending = b''
        oid = None
        try:
            while chunk := process.stdout.read(65536):
                pending += chunk
                while b'\0' in pending:
                    item, pending = pending.split(b'\0', 1)
                    if oid is None:
                        fields = item.lstrip(b'\n').split()
                        if not fields:
                            continue
                        if len(fields) != 5 or not fields[0].startswith(b':'):
                            raise GuardError('Unexpected Git change metadata.')
                        oid = fields[3].decode()
                    else:
                        name = os.fsdecode(item)
                        if (oid, name) not in legacy:
                            check_path(name)
                        oid = None
            if pending or oid is not None:
                raise GuardError('Truncated Git change metadata.')
        except BaseException:
            process.kill()
            process.wait()
            raise
        if process.wait():
            raise GuardError('Git history inspection failed.')
    check_history_blobs(revision, {oid for oid, _ in legacy})
    scan('git', '.', revision)


def pre_push():
    for line in sys.stdin:
        fields = line.split()
        if len(fields) != 4:
            raise GuardError('Malformed pre-push input.')
        _, local, _, remote = fields
        if set(local) == {'0'}:
            continue
        local = git('rev-parse', '--verify', local + '^{commit}').decode().strip()
        if set(remote) == {'0'}:
            revision = local
        else:
            exists = subprocess.run(['git', 'cat-file', '-e', remote + '^{commit}'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            revision = remote + '..' + local if exists.returncode == 0 else local
        history(revision)


def directory(path):
    root = Path(path)
    if not root.is_dir() or root.is_symlink():
        raise GuardError('Directory scan requires a real directory.')
    for folder, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            item = Path(folder) / name
            relative = item.relative_to(root).as_posix()
            check_path(relative)
            if item.is_symlink():
                raise GuardError('Symlink blocked: ' + repr(relative))
            if not item.is_dir() and not item.is_file():
                raise GuardError('Non-regular file blocked: ' + repr(relative))
            if item.is_file():
                check_file(item, relative)
    scan('dir', root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    sub.add_parser('staged')
    sub.add_parser('pre-push')
    sub.add_parser('history').add_argument('revision', nargs='?', default='--all')
    sub.add_parser('directory').add_argument('path')
    args = parser.parse_args()
    try:
        if args.mode == 'staged':
            staged()
        elif args.mode == 'pre-push':
            pre_push()
        elif args.mode == 'history':
            history(args.revision)
        else:
            directory(args.path)
    except (GuardError, OSError) as exc:
        print(str(exc) if isinstance(exc, GuardError) else 'Secret guard I/O failure; blocked.', file=sys.stderr)
        return 1
    print('Secret guard passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
