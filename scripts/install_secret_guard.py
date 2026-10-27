#!/usr/bin/env python3
"""Install the pinned scanner and opt this checkout into repository hooks."""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

from secret_guard import VERSION, ROOT

ARCHIVES = {
    'x86_64': ('linux_x64', '551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb'),
    'aarch64': ('linux_arm64', 'e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080'),
}


def install():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools-only', action='store_true')
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() not in ARCHIVES:
        parser.error('The pinned installer supports Linux x86_64 and aarch64.')
    if not args.tools_only:
        configured = subprocess.run(['git', 'config', '--get', 'core.hooksPath'], cwd=ROOT,
                                    text=True, capture_output=True).stdout.strip()
        if configured and (ROOT / configured).resolve() != (ROOT / '.githooks').resolve():
            parser.error('Existing core.hooksPath must be integrated manually; nothing overwritten.')
        hooks = subprocess.check_output(['git', 'rev-parse', '--git-path', 'hooks'], cwd=ROOT, text=True).strip()
        if not configured and any(p.is_file() and not p.name.endswith('.sample') for p in (ROOT / hooks).glob('*')):
            parser.error('Existing Git hooks must be integrated manually; nothing overwritten.')
    flavor, expected = ARCHIVES[platform.machine()]
    url = 'https://github.com/gitleaks/gitleaks/releases/download/v%s/gitleaks_%s_%s.tar.gz' % (VERSION, VERSION, flavor)
    target = Path.home() / '.local/share/opend-us-options/gitleaks' / VERSION
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='gitleaks-install-') as tmp:
        archive = Path(tmp) / 'download.tar.gz'
        digest = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=60) as response, archive.open('wb') as output:
            while block := response.read(1024 * 1024):
                digest.update(block)
                output.write(block)
        if digest.hexdigest() != expected:
            parser.error('Gitleaks archive checksum mismatch; installation stopped.')
        with tarfile.open(archive) as tar:
            member = tar.getmember('gitleaks')
            if not member.isfile():
                parser.error('Gitleaks archive has no regular binary.')
            temporary = target / ('gitleaks.tmp-%s' % os.getpid())
            with tar.extractfile(member) as source, temporary.open('wb') as output:
                shutil.copyfileobj(source, output)
            temporary.chmod(0o755)
            temporary.replace(target / 'gitleaks')
    if not args.tools_only:
        for name in ('pre-commit', 'pre-push'):
            (ROOT / '.githooks' / name).chmod(0o755)
        subprocess.run(['git', 'config', '--local', 'core.hooksPath', str(ROOT / '.githooks')], cwd=ROOT, check=True)
    print('Installed Gitleaks ' + VERSION + ('; hooks enabled.' if not args.tools_only else '; hooks unchanged.'))


if __name__ == '__main__':
    install()
