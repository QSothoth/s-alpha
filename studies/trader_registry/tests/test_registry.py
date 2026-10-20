"""Registry identity, provenance and safe read-only interface checks."""
from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from studies.trader_registry.registry import DEFAULT_PATH, ROOT, load_registry, main, query


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_registry()
        cls.raw = json.loads(DEFAULT_PATH.read_text())

    def reject(self, mutate):
        data = copy.deepcopy(self.raw)
        mutate(data)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'registry.json'
            path.write_text(json.dumps(data))
            with self.assertRaises((ValueError, TypeError)):
                load_registry(path)

    def test_count_and_cohorts(self):
        self.assertEqual(len(self.rows), 35)
        self.assertEqual(len(query(self.rows, cohort='original_33')), 33)
        self.assertEqual({t.id for t in query(self.rows, cohort='additional_reference')}, {'qullamaggie', 'oliver_kell'})

    def test_identity_aliases(self):
        for row in self.rows:
            for alias in (row.id, row.name, *row.aliases):
                self.assertIn(row, query(self.rows, alias))
        self.assertEqual(query(self.rows, 'MARK')[0].id, 'mark_minervini')
        self.assertEqual(query(self.rows, 'WhiteBear')[0].id, 'adrian_law')
        for ident in ('j_law', 'adrian_law', 'judy_lai'):
            self.assertEqual(len(query(self.rows, ident)), 1)
        self.assertFalse(query(self.rows, 'no-such-trader'))

    def test_schema_rejections(self):
        mutations = [
            lambda d: d.update(schema_version=2),
            lambda d: d['traders'].append(copy.deepcopy(d['traders'][0])),
            lambda d: d['traders'][0].update(markets='not-a-list'),
            lambda d: d['traders'][0].update(extra='unexpected'),
            lambda d: d['traders'][0].update(dossier_path='../AGENTS.md'),
            lambda d: d['traders'][0].update(dossier_path='/etc/passwd'),
            lambda d: d['traders'][0].update(dossier_path='missing.md'),
            lambda d: d['traders'][0]['implementation'].update(status='PROVEN_ALPHA'),
            lambda d: d['traders'][0].update(source_urls=['javascript:bad']),
            lambda d: d['traders'][1]['aliases'].append(d['traders'][0]['id']),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.reject(mutation)

    def test_unimplemented_not_advertised_as_code(self):
        for row in self.rows:
            if row.implementation.status in {'REFERENCE_ONLY_NOT_IMPLEMENTED', 'SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION', 'HISTORICAL_RESEARCH_BRANCH_ONLY'}:
                self.assertFalse(row.implementation.code_paths)
            self.assertTrue(row.missing_rules)
            self.assertTrue(row.next_steps)

    def test_status_code_contract(self):
        def missing_code(data):
            row = next(r for r in data['traders'] if r['id'] == 'martin_luk')
            row['implementation']['code_paths'] = []
        self.reject(missing_code)
        def invented_code(data):
            row = next(r for r in data['traders'] if r['id'] == 'judy_lai')     # an unimplemented record
            row['implementation']['code_paths'] = ['studies/martin_luk/luk.py']
        self.reject(invented_code)

    def test_source_files_and_dossier_manifest(self):
        base = DEFAULT_PATH.parent / 'dossiers'
        manifest = json.loads((base / 'MANIFEST.json').read_text())
        self.assertEqual(manifest['person_dossiers'], 35)
        self.assertEqual({p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file()}, {'MANIFEST.json'} | {r['path'] for r in manifest['files']})
        for item in manifest['files']:
            content = (base / item['path']).read_bytes()
            self.assertEqual(len(content), item['bytes'], item['path'])
            self.assertEqual(hashlib.sha256(content).hexdigest(), item['sha256'], item['path'])
        self.assertEqual(len({t.dossier_path for t in self.rows}), 35)

    def test_generated_index_is_current(self):
        from studies.trader_registry.render_index import render
        self.assertEqual(DEFAULT_PATH.with_name('INDEX_CN.md').read_text(), render())

    def test_read_only_cli_json(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['Mark', '--json']), 0)
        self.assertEqual(json.loads(output.getvalue())[0]['id'], 'mark_minervini')
        output = io.StringIO()
        with redirect_stdout(output):
            main(['--cohort', 'additional_reference'])
        self.assertEqual(len(output.getvalue().splitlines()), 2)

    def test_typed_records_are_immutable(self):
        from dataclasses import FrozenInstanceError
        with self.assertRaises(FrozenInstanceError):
            self.rows[0].name = "Changed"


if __name__ == '__main__':
    unittest.main()
