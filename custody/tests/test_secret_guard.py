import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts.secret_guard import VERSION

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts' / 'secret_guard.py'
SCANNER = Path.home() / '.local/share/opend-us-options/gitleaks' / VERSION / 'gitleaks'


@unittest.skipUnless(SCANNER.is_file(), 'Install the pinned scanner with scripts/install_secret_guard.py --tools-only')
class SecretGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='secret-guard-test-')
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.script = SCRIPT
        self.git('init', '-q')
        self.git('config', 'user.name', 'Guard Test')
        self.git('config', 'user.email', 'guard@example.invalid')
        self.git('config', 'core.hooksPath', str(self.repo / 'disabled-hooks'))

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo, stderr=subprocess.DEVNULL).decode().strip()

    def file(self, name, content):
        target = self.repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def guard(self, mode, *args, input=None, env=None):
        return subprocess.run([sys.executable, str(self.script), mode, *args], cwd=self.repo,
                              capture_output=True, text=True, input=input, env=env)

    def assert_blocked(self, result, secret=None):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        if secret:
            self.assertNotIn(secret, result.stdout + result.stderr)

    def token(self):
        return '_'.join(('SPT', 'Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv'))

    def baseline(self):
        self.file('safe.txt', 'ordinary text\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Baseline')
        return self.git('rev-parse', 'HEAD')

    def test_clean_files_and_empty_example_pass(self):
        self.file('safe.py', 'import os\n')
        self.file('.env.example', '# FUTU_TRADE_PASSWORD=\n')
        self.git('add', '.')
        result = self.guard('staged')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_forced_sensitive_filename_is_rejected(self):
        self.file('.gitignore', '.env\n')
        self.file('.env', 'harmless=fixture\n')
        self.git('add', '-f', '.env')
        self.assert_blocked(self.guard('staged'))

    def test_index_is_scanned_even_when_worktree_is_cleaned(self):
        secret = self.token()
        path = self.file('settings.py', 'token = ' + repr(secret) + '\n')
        self.git('add', 'settings.py')
        path.write_text('token = None\n')
        self.assert_blocked(self.guard('staged'), secret)

    def test_dirty_secret_not_in_index_does_not_block_clean_commit(self):
        path = self.file('settings.py', 'token = None\n')
        self.git('add', 'settings.py')
        path.write_text('token = ' + repr(self.token()) + '\n')
        result = self.guard('staged')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_futu_literal_and_md5_are_rejected_without_echo(self):
        for key, secret in [('FUTU_TRADE_PASSWORD', 'unit-' + 'private-passphrase'),
                            ('FUTU_TRADE_PASSWORD_MD5', 'a3b4' * 8)]:
            with self.subTest(key=key):
                self.file('settings.py', key + ' = ' + repr(secret) + '\n')
                self.git('add', 'settings.py')
                self.assert_blocked(self.guard('staged'), secret)

    def test_unquoted_shell_passwords_are_rejected(self):
        for key in ('FUTU_TRADE_PASSWORD', 'FUTU_TRADE_PASSWORD_MD5'):
            with self.subTest(key=key):
                secret = 'b4c5' * 8
                self.file('settings.sh', 'export ' + key + '=' + secret + '\n')
                self.git('add', 'settings.sh')
                self.assert_blocked(self.guard('staged'), secret)

    def test_checksum_exception_does_not_disable_api_key_detection(self):
        digest = '01a23b45c67d89ef' * 4
        self.file('pins.json', '{"case_keys_sha256": "' + digest + '"}\n')
        self.git('add', '.')
        clean = self.guard('staged')
        self.assertEqual(clean.returncode, 0, clean.stderr)
        secret = ''.join(('Ab3Cd4Ef5Gh6Ij7Kl8M', 'n9Op0Qr1St2Uv6Wx5Yz4'))
        self.file('settings.py', 'api_key = ' + repr(secret) + '\n')
        self.git('add', '.')
        self.assert_blocked(self.guard('staged'), secret)

    def test_merge_only_secret_is_scanned(self):
        base = self.baseline()
        self.git('checkout', '-qb', 'right')
        self.file('right.txt', 'right\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Right')
        self.git('checkout', '-qb', 'left', base)
        self.file('left.txt', 'left\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Left')
        self.git('merge', '--no-ff', '--no-commit', 'right')
        secret = self.token()
        self.file('merge.py', 'token = ' + repr(secret) + '\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Merge fixture')
        self.git('rm', 'merge.py')
        self.git('commit', '-qm', 'Remove fixture')
        self.assert_blocked(self.guard('history', base + '..' + self.git('rev-parse', 'HEAD')), secret)

    def test_inline_allow_comment_cannot_suppress_secret(self):
        secret = self.token()
        self.file('settings.py', 'token = ' + repr(secret) + ' # gitleaks:allow\n')
        self.git('add', '.')
        self.assert_blocked(self.guard('staged'), secret)

    def test_missing_scanner_blocks(self):
        env = dict(os.environ, GITLEAKS_BIN=str(self.repo / 'missing-scanner'))
        self.assert_blocked(self.guard('staged', env=env))

    def test_history_catches_secret_deleted_in_later_commit(self):
        base = self.baseline()
        secret = self.token()
        self.file('settings.py', 'token = ' + repr(secret) + '\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Add fixture')
        self.git('rm', 'settings.py')
        self.git('commit', '-qm', 'Remove fixture')
        head = self.git('rev-parse', 'HEAD')
        for remote in (base, '0' * 40):
            with self.subTest(remote=remote):
                data = 'refs/heads/main %s refs/heads/main %s\n' % (head, remote)
                self.assert_blocked(self.guard('pre-push', input=data), secret)

    def test_binary_diff_attribute_cannot_hide_secret(self):
        base = self.baseline()
        secret = self.token()
        self.file('.gitattributes', '*.txt -diff\n')
        self.file('settings.txt', secret + '\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Binary-marked fixture')
        self.assert_blocked(self.guard('history', base + '..' + self.git('rev-parse', 'HEAD')), secret)

    def test_history_catches_sensitive_file_deleted_in_later_commit(self):
        base = self.baseline()
        self.file('.env', 'harmless fixture\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Add fixture')
        self.git('rm', '.env')
        self.git('commit', '-qm', 'Remove fixture')
        head = self.git('rev-parse', 'HEAD')
        self.assert_blocked(self.guard('history', base + '..' + head))

    def test_directory_and_symlinks_are_rejected(self):
        release = self.repo / 'release'
        release.mkdir()
        secret = self.token()
        self.file('release/data.csv', 'value\n' + secret + '\n')
        self.assert_blocked(self.guard('directory', str(release)), secret)
        (release / 'data.csv').unlink()
        (release / 'outside').symlink_to('/dev/null')
        self.assert_blocked(self.guard('directory', str(release)))

    def test_binary_and_zip_blobs_are_blocked_even_after_deletion(self):
        import io
        import zipfile
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('settings.txt', self.token())
        for content in (b'\0' + self.token().encode(), archive.getvalue()):
            with self.subTest(kind=content[:2]):
                self.git('reset', '--hard', '-q') if (self.repo / 'safe.txt').exists() else self.baseline()
                base = self.git('rev-parse', 'HEAD')
                path = self.repo / 'disguised.txt'
                path.write_bytes(content)
                self.git('add', '.')
                self.assert_blocked(self.guard('staged'), self.token())
                self.git('commit', '-qm', 'Opaque fixture')
                self.git('rm', 'disguised.txt')
                self.git('commit', '-qm', 'Remove fixture')
                head = self.git('rev-parse', 'HEAD')
                self.assert_blocked(self.guard('history', base + '..' + head), self.token())

    def test_legacy_exception_is_exact_and_history_only(self):
        import gzip
        import json
        base = self.baseline()
        path = self.repo / 'legacy.csv.gz'
        path.write_bytes(gzip.compress(b'price\n1.0\n', mtime=0))
        self.git('add', 'legacy.csv.gz')
        self.git('commit', '-qm', 'Old public fixture')
        known = self.git('rev-parse', 'HEAD')
        oid = self.git('rev-parse', 'HEAD:legacy.csv.gz')
        shutil.copytree(ROOT / 'scripts', self.repo / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copyfile(ROOT / '.gitleaks.toml', self.repo / '.gitleaks.toml')
        (self.repo / 'scripts' / 'legacy_public_blobs.json').write_text(
            json.dumps([{'oid': oid, 'path': 'legacy.csv.gz'}]))
        self.script = self.repo / 'scripts' / 'secret_guard.py'
        allowed = self.guard('history', base + '..' + known)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.git('mv', 'legacy.csv.gz', '.env')
        self.git('commit', '-qm', 'Wrong path fixture')
        self.assert_blocked(self.guard('history', base + '..' + self.git('rev-parse', 'HEAD')))
        self.git('reset', '--hard', '-q', known)
        path.write_bytes(gzip.compress(b'price\n2.0\n', mtime=0))
        self.git('add', 'legacy.csv.gz')
        self.assert_blocked(self.guard('staged'))
        self.git('commit', '-qm', 'Changed legacy fixture')
        self.assert_blocked(self.guard('history', base + '..' + self.git('rev-parse', 'HEAD')))

    def test_installed_hook_blocks_real_push(self):
        self.baseline()
        self.file('settings.py', 'token = ' + repr(self.token()) + '\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Secret fixture')
        self.git('rm', 'settings.py')
        self.git('commit', '-qm', 'Remove fixture')
        shutil.copytree(ROOT / 'scripts', self.repo / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT / '.githooks', self.repo / '.githooks')
        shutil.copyfile(ROOT / '.gitleaks.toml', self.repo / '.gitleaks.toml')
        self.git('config', 'core.hooksPath', str(self.repo / '.githooks'))
        with tempfile.TemporaryDirectory(prefix='secret-guard-remote-') as remote:
            subprocess.run(['git', 'init', '--bare', '-q', remote], check=True)
            result = subprocess.run(['git', 'push', remote, 'HEAD:refs/heads/main'], cwd=self.repo,
                                    capture_output=True, text=True)
            self.assert_blocked(result, self.token())
            self.assertNotEqual(subprocess.run(['git', '--git-dir', remote, 'show-ref', '--verify',
                                               'refs/heads/main'], capture_output=True).returncode, 0)

    def test_installed_hook_blocks_real_commit(self):
        shutil.copytree(ROOT / 'scripts', self.repo / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT / '.githooks', self.repo / '.githooks')
        shutil.copyfile(ROOT / '.gitleaks.toml', self.repo / '.gitleaks.toml')
        self.git('config', 'core.hooksPath', str(self.repo / '.githooks'))
        self.file('settings.py', 'token = ' + repr(self.token()) + '\n')
        self.git('add', 'settings.py')
        result = subprocess.run(['git', 'commit', '-qm', 'Blocked fixture'], cwd=self.repo,
                                capture_output=True, text=True)
        self.assert_blocked(result, self.token())
        self.assertNotEqual(subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], cwd=self.repo,
                                          capture_output=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
