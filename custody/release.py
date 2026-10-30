"""Build a checked custody dataset archive without publishing it."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

from .dataset import Dataset, check, sha256_file

METADATA = frozenset(('manifest.json', 'cases.json', 'CHECKSUMS.sha256', 'README.md', 'README_CN.md'))
MARKET_PATH = re.compile(r'(?:underlying|option)/US\.[A-Z0-9.\-]+\.csv\Z')
GUARD = Path(__file__).resolve().parents[1] / 'scripts' / 'secret_guard.py'


class ReleaseError(ValueError):
    """The dataset cannot be safely packaged."""


def _inventory(root):
    files = set()
    if root.is_symlink() or not root.is_dir():
        raise ReleaseError('dataset must be a real directory')
    for directory, folders, names in os.walk(root, followlinks=False):
        for name in folders + names:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise ReleaseError('symlinks and special files are forbidden')
            relative = path.relative_to(root).as_posix()
            if stat.S_ISDIR(mode):
                if relative not in ('underlying', 'option'):
                    raise ReleaseError('unexpected directory in dataset')
            else:
                if relative not in METADATA and not MARKET_PATH.fullmatch(relative):
                    raise ReleaseError('unexpected file in dataset')
                files.add(relative)
    return files


def _validated_files(root):
    files = _inventory(root)
    try:
        if not check(root)['ok']:
            raise ReleaseError('dataset validation failed')
        dataset = Dataset(root)
        pinned = {p.relative_to(dataset.root).as_posix() for p in dataset._pinned}
        if files - METADATA != pinned - METADATA:
            raise ReleaseError('market files must match the checksum inventory')
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise ReleaseError('dataset validation or checksum inventory failed') from exc
    return files


def _copy_regular(root_fd, relative, destination):
    parts = Path(relative).parts
    parent_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = child_fd
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        with os.fdopen(fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ReleaseError('source file changed during packaging')
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as target:
                shutil.copyfileobj(source, target, length=1 << 20)
    finally:
        os.close(parent_fd)


def package(dataset, output):
    root, output = Path(dataset).absolute(), Path(output).absolute()
    if output.suffix != '.zip':
        raise ReleaseError('output must have a .zip suffix')
    if output.exists() or output.is_symlink():
        raise ReleaseError('output already exists')
    if output.resolve().is_relative_to(root.resolve()):
        raise ReleaseError('output must be outside the dataset')
    files = _validated_files(root)
    with tempfile.TemporaryDirectory(prefix='custody-release-') as temporary:
        staging = Path(temporary) / root.name
        staging.mkdir()
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for relative in sorted(files):
                _copy_regular(root_fd, relative, staging / relative)
        finally:
            os.close(root_fd)
        if _validated_files(staging) != files:
            raise ReleaseError('dataset changed during packaging')
        result = subprocess.run([sys.executable, str(GUARD), 'directory', str(staging)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode:
            raise ReleaseError('secret scan failed; archive was not created')
        with tempfile.TemporaryFile() as archive_file:
            with zipfile.ZipFile(archive_file, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for relative in sorted(files):
                    archive.write(staging / relative, arcname=root.name + '/' + relative)
            archive_file.seek(0)
            with output.open('xb') as target:
                try:
                    shutil.copyfileobj(archive_file, target, length=1 << 20)
                except BaseException:
                    output.unlink()
                    raise
    return {'archive': str(output), 'sha256': sha256_file(output), 'files': len(files)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    try:
        result = package(args.dataset, args.out)
    except (ReleaseError, OSError, ValueError):
        print('Release blocked: validation, file policy, secret scan, or output creation failed.', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
