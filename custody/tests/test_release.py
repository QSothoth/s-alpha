import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).parent))
from helpers import write_dataset
from test_dataset import spy_cases
from custody.dataset import sha256_file, write_checksums
from custody.release import ReleaseError, main, package
from scripts.secret_guard import VERSION


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'dataset'
        write_dataset(self.root, spy_cases())
        self.output = Path(self.tmp.name) / 'release.zip'

    def test_valid_archive_contains_only_checked_files(self):
        with patch('custody.release.subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as scan:
            result = package(self.root, self.output)
        self.assertEqual(result['sha256'], sha256_file(self.output))
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(set(archive.namelist()), {
                'dataset/manifest.json', 'dataset/cases.json', 'dataset/CHECKSUMS.sha256',
                'dataset/underlying/US.SPY.csv', 'dataset/option/US.SPY260914C100000.csv',
                'dataset/option/US.SPY260914P100000.csv'})
        self.assertEqual(scan.call_args.args[0][-2], 'directory')

    def test_extra_file_is_rejected_even_when_checksum_pinned(self):
        (self.root / '.env').write_text('unit-test marker\n')
        for pinned in (False, True):
            with self.subTest(pinned=pinned):
                if pinned:
                    with (self.root / 'CHECKSUMS.sha256').open('a') as target:
                        target.write(sha256_file(self.root / '.env') + '  .env\n')
                with self.assertRaises(ReleaseError):
                    package(self.root, self.output)
                self.assertFalse(self.output.exists())

    def test_unpinned_market_file_is_rejected(self):
        (self.root / 'underlying' / 'US.EXTRA.csv').write_text('unit-test marker\n')
        with self.assertRaises(ReleaseError):
            package(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_binary_parquet_twin_is_not_published(self):
        (self.root / 'underlying' / 'US.SPY.parquet').write_bytes(b'PAR1\x00fixture')
        with self.assertRaises(ReleaseError):
            package(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_symlink_file_and_directory_are_rejected(self):
        external = Path(self.tmp.name) / 'external'
        external.mkdir()
        for destination in (self.root / 'README.md', self.root / 'extra'):
            with self.subTest(destination=destination.name):
                destination.symlink_to(external)
                with self.assertRaises(ReleaseError):
                    package(self.root, self.output)
                destination.unlink()
        if hasattr(os, 'mkfifo'):
            os.mkfifo(self.root / 'README.md')
            with self.assertRaises(ReleaseError):
                package(self.root, self.output)

    def test_scan_failure_never_creates_archive_or_prints_metadata(self):
        marker = 'synthetic-' + 'sensitive-marker'
        manifest = json.loads((self.root / 'manifest.json').read_text())
        manifest['private_note'] = marker
        (self.root / 'manifest.json').write_text(json.dumps(manifest))
        write_checksums(self.root)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch('custody.release.subprocess.run', return_value=subprocess.CompletedProcess([], 1)):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(main(['--dataset', str(self.root), '--out', str(self.output)]), 1)
        self.assertNotIn(marker, stdout.getvalue() + stderr.getvalue())
        self.assertFalse(self.output.exists())

    @unittest.skipUnless((Path.home() / '.local/share/opend-us-options/gitleaks' / VERSION / 'gitleaks').is_file(),
                         'Install the pinned scanner before testing release content scanning')
    def test_real_scanner_checks_metadata_before_creating_archive(self):
        clean_output = Path(self.tmp.name) / 'clean.zip'
        package(self.root, clean_output)
        self.assertTrue(zipfile.is_zipfile(clean_output))
        manifest = json.loads((self.root / 'manifest.json').read_text())
        manifest['private_note'] = '_'.join(('SPT', 'Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv'))
        (self.root / 'manifest.json').write_text(json.dumps(manifest))
        write_checksums(self.root)
        with self.assertRaisesRegex(ReleaseError, 'secret scan failed'):
            package(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_output_is_preserved(self):
        self.output.write_bytes(b'existing archive')
        with self.assertRaises(ReleaseError):
            package(self.root, self.output)
        self.assertEqual(self.output.read_bytes(), b'existing archive')

    def test_changed_snapshot_fails_revalidation(self):
        from custody.release import _copy_regular

        def change_copy(root_fd, relative, destination):
            _copy_regular(root_fd, relative, destination)
            if relative.endswith('US.SPY.csv'):
                with destination.open('a') as target:
                    target.write('changed\n')

        with patch('custody.release._copy_regular', side_effect=change_copy):
            with self.assertRaises(ReleaseError):
                package(self.root, self.output)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
