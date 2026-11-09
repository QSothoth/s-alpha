import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from studies.trader_replication import compare, systems
from studies.martin_luk import ie47_e1 as M


class RegistrationTests(unittest.TestCase):
    def test_research_version_keeps_frozen_martin_and_default_board_unchanged(self):
        master = systems.get('martin_luk')
        self.assertEqual((master.version, master.status), ('R74 + S7', 'frozen'))
        research = systems.get('martin_luk_ie47')
        self.assertEqual((research.trader, research.version, research.status), ('martin_luk', 'IE47 + E5', 'research'))
        self.assertEqual(research.markets, ('us',))
        self.assertEqual(research.comparison.name, 'e5_compare.json')
        self.assertNotIn(research.id, {s.id for s in systems.board('us')})
        self.assertIn(research.id, {s.id for s in systems.board('us', versions=True)})
        self.assertNotIn(research.id, {s.id for s in systems.board('cn', versions=True)})
        st, cfg = research.load()
        self.assertIsInstance(st, M.IE47Study)
        expected = json.loads((M.STUDY.reports/'e5_selected.json').read_text())['config']
        self.assertEqual(cfg, expected)
        self.assertIn(research.id, compare.traders())

    def test_independent_comparison_is_used_and_stale_code_is_refused(self):
        from studies.trader_replication import runner
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'e5_compare.json'
            row = dict(by_year={'2024': .2}, run=dict(config_digest=compare.config_digest({}), code_digest='E5'))
            path.write_text(json.dumps({'toy': {'markets': {'us': row}}}), encoding='utf-8')
            system = SimpleNamespace(id='toy', config={}, comparison=path)
            with patch.object(compare, 'code_digest', return_value='E5'):
                self.assertEqual(runner.reference(system, 'us'), row)
            with patch.object(compare, 'code_digest', return_value='different'):
                self.assertIsNone(runner.reference(system, 'us'))


if __name__ == '__main__':
    unittest.main()
