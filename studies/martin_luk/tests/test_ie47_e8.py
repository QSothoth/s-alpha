"""E8 regime risk scale: prior-close QQQ vs 21 EMA and prior-night pool breadth; written before the code."""
from dataclasses import replace
import unittest

import numpy as np

from studies.martin_luk import ie47_e1 as M
from studies.martin_luk.tests.test_ie47_e1 import arrays
from studies.trader_replication import standard_indicators as SI


class E8ScaleTests(unittest.TestCase):
    def test_qqq_scale_uses_previous_close_only(self):
        q = np.r_[np.full(30, 100.), 90, 110, 110]
        s = M.regime_scale(q, np.full(len(q), 10), dict(qqq=True, breadth=False))
        e = SI.ema(q, 21)
        for d in range(1, len(q)):
            self.assertEqual(s[d], 1. if q[d-1] > e[d-1] else .5)
        q2 = q.copy()
        q2[-1] = 1
        np.testing.assert_array_equal(M.regime_scale(q2, np.full(len(q), 10), dict(qqq=True, breadth=False)), s)

    def test_breadth_compares_previous_night_with_its_twenty_night_mean(self):
        n = np.r_[np.full(25, 10.), 5, 20, 3]
        s = M.regime_scale(np.full(len(n), 100.), n, dict(qqq=False, breadth=True))
        self.assertEqual(s[26], .5)   # night 25 had 5 < mean
        self.assertEqual(s[27], 1.)   # night 26 had 20 >= mean
        self.assertEqual(s[25], 1.)   # flat 10 >= 10
        n2 = n.copy()
        n2[-1] = 99
        np.testing.assert_array_equal(M.regime_scale(np.full(len(n), 100.), n2, dict(qqq=False, breadth=True)), s)

    def test_product_and_rules(self):
        q = np.r_[np.full(30, 100.), 90, 90]
        n = np.r_[np.full(30, 10.), 5, 5]
        s = M.regime_scale(q, n, dict(qqq=True, breadth=True))
        self.assertEqual(s[-1], .25)
        for k in M.E8:
            self.assertEqual(M.e8_rules(k), replace(M.e7_rules('E7a'), risk_scale='e8_scale'))
        self.assertEqual({k: v['pullback'] for k, v in M.E8.items()},
                         {'E8a': False, 'E8b': False, 'E8c': False, 'E8d': True})

    def test_build_sets_the_candidate_scale(self):
        a = arrays([(99, 100, 98, 99), (95, 105, 90, 104), (104, 105, 103, 104)], adr=20)
        a['_ie47'] = dict(picks={str(a['days'][0]): ['SYN_00']}, pool=np.ones((3, 1), bool),
                          qqq=np.array([100., 101., 102.]))
        for k in M.E8:
            book, rules, _, _ = M.IE47Study().build(a, {'candidate': k})
            self.assertEqual([len(x) for x in book], [0, 1, 0])
            self.assertEqual(rules, M.e8_rules(k))
            self.assertEqual(a['e8_scale'].shape, (3,))


if __name__ == '__main__':
    unittest.main()
