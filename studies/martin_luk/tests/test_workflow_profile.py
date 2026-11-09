import unittest
from unittest.mock import patch

from studies.martin_luk.workflow import bootstrap
from studies.martin_luk.workflow.version_profile import side_fit


class ProfileComparison(unittest.TestCase):
    def test_side_distribution_uses_both_directions(self):
        row = {'trader_sample_n': 20, 'entries': 100,
               'trader_side': {'long': {'fraction': .7}, 'short': {'fraction': .3}},
               'side': {'long': 70, 'short': 30}}
        self.assertEqual(side_fit(row, .2), '画像范围内')
        row['side'] = {'long': 100, 'short': 0}
        self.assertEqual(side_fit(row, .2), '画像范围外')
        row['trader_side'] = {'long': {'fraction': 1.0}}
        self.assertIn('无法判定', side_fit(row, .2))
        row['trader_sample_n'] = 0
        self.assertEqual(side_fit(row, .2), '无法判定')

    def test_g0_manifest_only_reads_annual_cards(self):
        card = {'return': 2.0, 'sources': {'return': 'source'}}
        config = {'behaviour_card': {'2024': card, '2026': card, 'by_state': {'2024': {}}}}
        written = {}
        with patch.object(bootstrap, 'write', side_effect=lambda path, value: written.update({path.name: value})), \
                patch.object(bootstrap.datasets, 'sha', return_value='sha'), \
                patch.object(bootstrap.pipeline, 'g0', return_value={'status': 'pass'}):
            result = bootstrap.source_card(config)
        self.assertEqual(result, {'status': 'pass'})
        self.assertEqual(set(written['G0_manifest.json']['public']), {'2024', '2026'})


if __name__ == '__main__':
    unittest.main()
