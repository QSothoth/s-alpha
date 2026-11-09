"""Market labels are causal, discrete and frozen; no evaluation input is read."""
import unittest

import numpy as np

from studies.trader_replication import regime as R
from studies.trader_replication.config import validate_switch


def panel(n=170):
    t = np.arange(n)
    c = 50*np.exp(.003*t[:, None]+.16*np.sin(t[:, None]/11+np.arange(4)))
    return dict(days=np.array([str(np.datetime64('2024-01-01')+i) for i in t]),
        codes=np.array(list('ABCD')), close=c, open=c, high=c*1.01, low=c*.99,
        raw=c, to20=np.full_like(c, 30e6), ledger=object(), legs=object())


class RegimeTests(unittest.TestCase):
    def test_prefix_invariance_for_every_producer(self):
        A = panel()
        for producer in ('idx_ema', 'breadth', 'smc'):
            full = R.states(A, dict(producer=producer))
            for k in (20, 55, 119):
                cut = {key: value[:k] if isinstance(value, np.ndarray) and key != 'codes' else value
                       for key, value in A.items()}
                short = R.states(cut, dict(producer=producer))
                np.testing.assert_array_equal(full['label'][:k], short['label'])
            self.assertEqual(full['label'].dtype, np.int8)
            self.assertEqual(set(full['counts']), set(R.NAMES))
            self.assertNotIn('probability', full)

    def test_current_day_changes_cannot_change_current_label(self):
        for producer in ('idx_ema', 'breadth', 'smc'):
            A = panel()
            expected = R.states(A, dict(producer=producer))['label']
            A['close'][100:] *= .1
            A['high'][100:] *= .1
            A['low'][100:] *= .1
            np.testing.assert_array_equal(expected[:101], R.states(A, dict(producer=producer))['label'][:101])

    def test_episodes_cover_every_day_once(self):
        rows = R.episodes([0, 0, 1, 2, 2, 0], list('abcdef'))
        self.assertEqual([(e['first'], e['last'], e['state']) for e in rows],
                         [(0, 1, 'up'), (2, 2, 'pullback'), (3, 4, 'weak'), (5, 5, 'up')])
        self.assertEqual(R.episodes([], []), [])
        out = R.states(panel())
        self.assertEqual(sum(r['days'] for r in out['counts'].values()), 170)
        self.assertEqual(sum(r['episodes'] for r in out['counts'].values()), len(out['episodes']))

    def test_determinism_sha_and_market_only_inputs(self):
        A = panel()
        a, b = R.states(A), R.states(A)
        np.testing.assert_array_equal(a['label'], b['label'])
        self.assertEqual(a['spec_sha'], b['spec_sha'])
        self.assertNotEqual(a['spec_sha'], R.states(A, dict(band=.02))['spec_sha'])
        with self.assertRaises(ValueError):
            R.states(A, dict(legs=[]))

    def test_stability_is_direct_agreement_not_probability(self):
        A = panel()
        report = R.stability(A)
        base = R.states(A)['label']
        expected = [float(np.mean(base == R.states(A, s)['label'])) for _, s in R.perturbations(None)]
        self.assertEqual([r['agreement'] for r in report['variants']], expected)
        self.assertEqual(report['minimum'], min(expected))
        self.assertEqual(report['ok'], min(expected) >= .9)

    def test_sourced_controls_cannot_change_stock_rank_or_stop(self):
        good = dict(controls=[dict(field='risk_mult', quote='reduce risk',
            values=dict(up=1., pullback=1.6, weak=.5))])
        self.assertTrue(validate_switch(good, 'Always reduce risk in weakness.'))
        for field in ('rank', 'stop_width'):
            with self.assertRaises(ValueError):
                validate_switch(dict(controls=[dict(good['controls'][0], field=field)]), 'reduce risk')
        with self.assertRaises(ValueError):
            validate_switch(good, 'a different statement')
        with self.assertRaises(ValueError):
            validate_switch(dict(controls=good['controls']*3), 'reduce risk')

    def test_smc_waits_for_confirmed_pivot_then_recognizes_both_breaks(self):
        close = np.r_[np.arange(10., 21.), np.full(10, 15.), 21., np.full(10, 21.), 14., np.full(11, 14.)]
        A = dict(days=np.arange(len(close)), indices={'QQQ': dict(close=close, high=close, low=close)})
        labels = R.states(A, dict(producer='smc', source='QQQ'))['label']
        self.assertEqual(labels[21], R.PULLBACK)
        self.assertEqual(labels[22], R.UP)       # day 21 close breaks the confirmed high; used next session
        self.assertEqual(labels[33], R.WEAK)    # first lower break after bullish structure is CHoCH


if __name__ == '__main__':
    unittest.main()
