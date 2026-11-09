"""E7 timing: pullback trigger, add-on-profit and feedback sizing; written before the implementation."""
from dataclasses import replace
import unittest

import numpy as np

from studies.martin_luk import ie47_e1 as M
from studies.martin_luk.tests.test_ie47_e1 import arrays, replay


def with_emas(a, e9, e21):
    a['e9'] = np.asarray(e9, float).reshape(a['close'].shape)
    a['e21'] = np.asarray(e21, float).reshape(a['close'].shape)
    return a


class E7PullbackTests(unittest.TestCase):
    def book(self, a, pullback=True):
        spec = dict(M.E6['E6c'], pullback=pullback)
        return M.entry_book(a, {str(a['days'][0]): ['SYN_00']}, **spec)

    def test_pullback_reclaim_triggers_without_breaking_previous_high(self):
        # day 1: high 101 < previous high 105, low touches 9 EMA 99, closes 100.5 above it and above the open
        a = with_emas(arrays([(100, 105, 98, 100), (99.5, 101, 98.8, 100.5)], adr=10), [99, 99], [97, 97])
        book, _, _ = self.book(a)
        self.assertEqual(len(book[1]), 1)
        self.assertEqual(book[1][0][3], 100.5)
        self.assertAlmostEqual(book[1][0][4], 98.8)
        self.assertEqual(book[1][0][5], M.PB_KIND)
        self.assertFalse(self.book(a, pullback=False)[0][1])

    def test_each_pullback_condition_is_required(self):
        base = [(100, 105, 98, 100), (99.5, 101, 98.8, 100.5)]
        cases = {'no touch': dict(low=99.2), 'close below ema': dict(close=98.9, open=98.85),
                 'red candle': dict(open=100.8), 'ema9 below ema21': dict(e21=99.5)}
        for name, change in cases.items():
            with self.subTest(name):
                a = with_emas(arrays(base, adr=10), [99, 99], [97, change.get('e21', 97)])
                for k in ('low', 'close', 'open'):
                    if k in change:
                        a[k][1, 0] = change[k]
                self.assertFalse(self.book(a)[0][1])

    def test_breakout_still_triggers_and_one_entry_per_observation(self):
        a = with_emas(arrays([(100, 105, 98, 100), (104, 107, 103, 106), (104, 108, 103.5, 107)], adr=10),
                      [99, 99, 99], [97, 97, 97])
        book, _, _ = self.book(a)
        self.assertEqual([len(r) for r in book], [0, 1, 0])
        self.assertEqual(book[1][0][5], M.CLOSE_KIND)

    def test_wide_pullback_stop_is_capped_like_e6c(self):
        a = with_emas(arrays([(100, 105, 90, 100), (95, 101, 90, 100.5)], adr=6), [92, 92], [91, 91])
        self.assertAlmostEqual(self.book(a)[0][1][0][4], 100.5*(1-.03))


class E7SizingTests(unittest.TestCase):
    def test_candidates_and_rules(self):
        self.assertEqual(set(M.E7), {'E7a', 'E7b', 'E7c', 'E7d', 'E7e'})
        base = M.execution_rules('E5')
        a, b, c, d = (M.e7_rules(k) for k in ('E7a', 'E7b', 'E7c', 'E7d'))
        self.assertEqual((a.risk, a.add_signal, a.add_signal_profit, a.add_signal_max, a.add_signal_frac,
                          a.add_signal_stop, a.feedback), (.0025, 'always', True, 1, 1.0, 'keep', 0))
        self.assertEqual((b.risk, b.risk_low, b.feedback, b.add_signal), (.005, .0025, 5, ''))
        self.assertEqual((c.risk, c.risk_low, c.feedback, c.add_signal), (.0025, .00125, 5, 'always'))
        self.assertEqual(d, base)
        self.assertEqual(M.e7_rules('E7e'), c)
        self.assertEqual(replace(a, risk=base.risk, add_signal='', add_signal_profit=False, add_signal_max=0,
                                 add_signal_frac=0.0), base)

    def test_add_once_at_first_later_close_above_fill_stop_unchanged(self):
        a = arrays([(99, 100, 98, 99), (102, 105, 101, 104), (104, 104.5, 102, 103),
                    (103, 107, 102.5, 106), (106, 109, 105, 108)], adr=10)
        book = M.entry_book(a, {str(a['days'][0]): ['SYN_00']}, **M.E6['E6c'])[0]
        rules = replace(M.e7_rules('E7a'), trims=())
        ema = None
        a['always'] = np.ones_like(a['close'], bool)
        from studies.trader_replication import system as Y
        px = {k: a[k] for k in ('open', 'high', 'low', 'close', 'codes')}
        px['dates'] = a['days']
        e9 = np.full_like(a['close'], 90.)
        _, _, trades = Y.simulate(px, dict(e9=e9, below_e9=a['close'] < e9, always=a['always']),
                                  replace(rules, buy_cost=0, sell_cost=0, margin_rate=0), book,
                                  a['days'][0], a['days'][-1], audit=True)
        ex = trades[0]['executions']
        self.assertEqual([e['action'] for e in ex], ['entry', 'add', 'end'])
        self.assertEqual((ex[1]['time'], ex[1]['price']), (a['days'][3], 106.))
        self.assertAlmostEqual(ex[1]['shares'], ex[0]['shares'])
        self.assertEqual(trades[0]['stop'], 101.)

    def test_build_routes_e7(self):
        a = arrays([(99, 100, 98, 99), (95, 105, 90, 104), (104, 105, 103, 104)], adr=20)
        a['_ie47'] = dict(picks={str(a['days'][0]): ['SYN_00']}, pool=np.ones((3, 1), bool))
        for k in M.E7:
            with self.subTest(k=k):
                book, rules, _, _ = M.IE47Study().build(dict(a), {'candidate': k})
                self.assertEqual([len(x) for x in book], [0, 1, 0])
                self.assertEqual(rules, M.e7_rules(k))
        self.assertTrue(M.IE47Study().named(a, None, 'always').all())


if __name__ == '__main__':
    unittest.main()
