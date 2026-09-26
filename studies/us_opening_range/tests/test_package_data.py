import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from studies.us_opening_range.package_data import package, research_snapshot, verified_files


class PackageDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'source-work'
        self.root.mkdir()
        (self.root / 'manifest.json').write_text(json.dumps({'role': 'test'}))
        (self.root / 'bars.csv').write_text('time,close\n09:35,1\n')
        self.checksums()
        self.output = self.base / 'release.zip'

    def checksums(self):
        lines = []
        for path in sorted(self.root.iterdir()):
            if path.name != 'CHECKSUMS.sha256':
                lines.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name)
        (self.root / 'CHECKSUMS.sha256').write_text('\n'.join(lines) + '\n')

    def test_roundtrip_preserves_original_and_sidecar(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        result = package(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(set(archive.namelist()), {'source-work/' + name for name in before})
            for name, contents in before.items():
                self.assertEqual(archive.read('source-work/' + name), contents)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        digest = hashlib.sha256(self.output.read_bytes()).hexdigest()
        self.assertEqual(result['sha256'], digest)
        self.assertEqual((self.base / 'release.zip.sha256').read_text(), digest + '  release.zip\n')

    def test_no_overwrite_archive_or_sidecar(self):
        self.output.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):
            package(self.root, self.output)
        self.assertEqual(self.output.read_bytes(), b'keep')
        other = self.base / 'another.zip'
        other.with_name(other.name + '.sha256').write_text('keep')
        with self.assertRaises(FileExistsError):
            package(self.root, other)
        self.assertFalse(other.exists())

    def test_changed_or_extra_source_is_rejected_before_zip(self):
        (self.root / 'bars.csv').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            package(self.root, self.output)
        self.assertFalse(self.output.exists())
        self.checksums()
        (self.root / 'extra.csv').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'coverage'):
            verified_files(self.root)

    def test_unsafe_duplicate_and_symlink_rejected(self):
        checksums = self.root / 'CHECKSUMS.sha256'
        original = checksums.read_text()
        for text in (original + original.splitlines()[0] + '\n', '0' * 64 + '  ../outside\n'):
            checksums.write_text(text)
            with self.assertRaisesRegex(ValueError, 'unsafe or duplicate'):
                verified_files(self.root)
        checksums.write_text(original)
        (self.root / 'link').symlink_to(self.root / 'bars.csv')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            verified_files(self.root)

    def test_archive_inside_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside source'):
            package(self.root, self.root / 'release.zip')

    def test_python_source_is_not_published_as_data(self):
        (self.root / 'engine.py').write_text('"""Synthetic code fixture."""\n')
        self.checksums()
        with self.assertRaisesRegex(ValueError, 'belongs in Git'):
            package(self.root, self.output)
        self.assertFalse(self.output.exists())


class ResearchSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / 'repo'
        self.study = self.repo / 'studies/us_opening_range'
        for folder in ('reports', 'notes'):
            (self.study / folder).mkdir(parents=True, exist_ok=True)
        (self.repo / 'data').mkdir()
        self.artifact = self.repo / 'data/test-events.jsonl'
        self.artifact.write_bytes(b'{"synthetic": true}\n')
        self.code = self.study / 'test_engine.py'
        self.code.write_text('"""Synthetic test fixture."""\n')
        (self.study / 'package_data.py').write_text('"""Synthetic packager fixture."""\n')
        self.prereg = self.study / 'notes/TEST_PREREG.md'
        self.prereg.write_text('Synthetic only.\n')
        self.report = {
            'study': 'TEST', 'preregistration_sha256': self.digest(self.prereg),
            'signal_events': {'path': 'data/test-events.jsonl', 'sha256': self.digest(self.artifact)},
            'code_sha256': {'studies/us_opening_range/test_engine.py': self.digest(self.code)},
        }
        self.report_path = self.study / 'reports/test.json'
        self.output = Path(self.temp.name) / 'new-snapshot'

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def run_snapshot(self):
        self.report_path.write_text(json.dumps(self.report))
        with patch('studies.us_opening_range.package_data.RESEARCH_REPORTS', {'test': self.digest(self.report_path)}):
            return research_snapshot(self.repo, self.output)

    def test_preserves_all_original_bytes_and_packaging_roundtrip(self):
        result = self.run_snapshot()
        self.assertEqual(result['files'], 5)
        for original in (self.report_path, self.artifact, self.prereg):
            copied = self.output / original.relative_to(self.repo)
            self.assertEqual(copied.read_bytes(), original.read_bytes())
        metadata = json.loads((self.output / 'manifest.json').read_text())
        self.assertEqual(metadata['role'], 'research/derived-signal-audit')
        code_name = self.code.relative_to(self.repo).as_posix()
        self.assertEqual(metadata['original_files_sha256'][code_name], self.digest(self.code))
        self.assertNotIn(code_name, metadata['archived_files_sha256'])
        self.assertFalse(list(self.output.rglob('*.py')))
        packaged = package(self.output, self.output.with_suffix('.zip'))
        self.assertEqual(packaged['files'], 5)

    def test_code_is_still_verified_even_though_not_copied(self):
        self.code.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            self.run_snapshot()
        self.assertFalse(self.output.exists())

    def test_mismatch_rejected_before_output(self):
        self.artifact.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            self.run_snapshot()
        self.assertFalse(self.output.exists())

    def test_refuses_existing_output(self):
        self.output.mkdir()
        (self.output / 'keep').write_text('preserve')
        with self.assertRaises(FileExistsError):
            self.run_snapshot()
        self.assertEqual((self.output / 'keep').read_text(), 'preserve')

    def test_unsafe_or_symlink_artifact_rejected(self):
        self.report['signal_events']['path'] = 'data/../data/test-events.jsonl'
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            self.run_snapshot()
        self.report['signal_events']['path'] = 'data/link.jsonl'
        (self.repo / 'data/link.jsonl').symlink_to(self.artifact)
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            self.run_snapshot()
        self.assertFalse(self.output.exists())

    def test_multiple_artifacts_or_changed_prereg_rejected(self):
        self.report['signals_artifact'] = dict(self.report['signal_events'])
        with self.assertRaisesRegex(ValueError, 'one local'):
            self.run_snapshot()
        del self.report['signals_artifact']
        self.prereg.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            self.run_snapshot()
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
