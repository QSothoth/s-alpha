"""Frozen real-data consistency checks required by WF00 (never fit a candidate)."""
from pathlib import Path
import unittest

import numpy as np

from studies.martin_luk.workflow import adapter as D
from studies.trader_replication import funnel, regime
from studies.trader_replication.config import Config


@unittest.skipUnless((D.REPORTS/'p5_work/accounts/S3_BOTH/summary.json').exists(), 'frozen artifacts unavailable')
class FrozenReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        panel, market = D.REPORTS/'u1_work/panel', D.REPORTS/'p3_work/market'
        cls.A = {key: np.load((panel if key in ('days', 'codes') else market)/(key+'.npy'), mmap_mode='r')
                 for key in ('days', 'codes', 'open', 'high', 'low', 'close')}
        cls.legs = D.read(D.HOME/'notes/legs_frozen.json')['legs']

    def test_every_early_and_peak_bit_matches_five_original_reports(self):
        expected = dict(master=(12, 11), X1_OPEN=(18, 6), S1_NOBLOCK=(22, 7),
                        S2_CLOSESTOP=(15, 9), S3_BOTH=(20, 13))
        for name, totals in expected.items():
            folder = 'controls/'+name if name in ('master', 'X1_OPEN') else 'accounts/'+name
            source = D.read(D.REPORTS/('p5_work/'+folder+'/summary.json'))['holding_coverage']['per_leg']
            rows = funnel.holding_coverage(self.A, D.load_account(name), D.rules_for(name), self.legs)
            self.assertEqual((sum(r['covered'] for r in rows), sum(r['peak_held'] for r in rows)), totals)
            for a, b in zip(rows, source):
                for key in ('key', 'any', 'covered', 'first_fill', 'offset', 'peak_shares', 'peak_held'):
                    self.assertEqual(a[key], b[key], (name, a['key'], key))

    def test_r74_flat_and_common_config_produce_identical_rules(self):
        from studies.trader_replication.martin import Martin
        old = D.read(D.REPORTS/'d1_work/master_metadata.json')['config']
        old['_market'] = 'us'
        flat = Config(old)
        wrapped = Config({key: dict(common=dict(flat[key]), by_state={}) for key in flat})
        self.assertEqual(flat.flat(), old)
        self.assertEqual(wrapped.flat(), old)
        self.assertEqual(Martin().trade(flat), Martin().trade(wrapped))

    def test_b4_matches_historical_producer_and_is_causal(self):
        from studies.martin_luk import p5_policy as P5
        A = dict(self.A, adr=np.load(D.REPORTS/'p3_work/market/adr.npy', mmap_mode='r'),
                 to20=np.load(D.REPORTS/'p3_work/market/to20.npy', mmap_mode='r'))
        A['nominations'] = D.indexed(A, D.REPORTS/'p5_work/accounts/S3_BOTH/nominations.json.gz')
        labels = regime.states(A, dict(producer='B4_PCT2'))['label']
        self.assertEqual(list(labels), D.read(D.REPORTS/'p5_work/regimes/B4_PCT2.json')['full_label'])
        end = 500
        short = {k: v[:end] if isinstance(v, np.ndarray) and k != 'codes' else v for k, v in A.items()}
        short['nominations'] = {t: cs for t, cs in A['nominations'].items() if t < end-1}
        np.testing.assert_array_equal(labels[:end], regime.states(short, dict(producer='B4_PCT2'))['label'])


if __name__ == '__main__':
    unittest.main()
