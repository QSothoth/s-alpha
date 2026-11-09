"""E6 close-entry stops: cap instead of skip; written before the implementation."""
import unittest

import numpy as np

from studies.martin_luk import ie47_e1 as M
from studies.martin_luk.tests.test_ie47_e1 import arrays, replay


class E6StopTests(unittest.TestCase):
    def book(self, a, candidate):
        return M.entry_book(a, {str(a['days'][0]): ['SYN_00']}, **M.E6[candidate])

    def test_candidates_are_fixed(self):
        self.assertEqual(set(M.E6), {'E6a', 'E6b', 'E6c', 'E6d'})
        self.assertEqual(M.E6['E6c']['observe'], 5)
        self.assertTrue(all(M.E6[k]['observe'] == 3 for k in ('E6a', 'E6b', 'E6d')))

    def test_inside_cap_keeps_the_e5_same_day_low_stop(self):
        # close 104, low 101: 2.9% <= min(5%, ADR 20 / 2): identical to E5.
        a = arrays([(99, 100, 98, 99), (102, 105, 101, 104)], adr=20)
        e5 = M.entry_book(a, {str(a['days'][0]): ['SYN_00']}, 3, close_confirmed=True)[0]
        for k in ('E6a', 'E6b', 'E6c'):
            with self.subTest(k=k):
                book = self.book(a, k)[0]
                self.assertEqual(book[1][0][3:5], e5[1][0][3:5])
                self.assertEqual(book[1][0][3:5], (104., 101.))

    def test_wide_stop_is_capped_not_skipped(self):
        # close 104, low 90: raw 13.5%; cap 5% (ADR 20) or 3% (E6d) or ADR/2 = 2% (ADR 4).
        for k, adr, width in (('E6a', 20, .05), ('E6c', 20, .05), ('E6d', 20, .03), ('E6a', 4, .02), ('E6d', 4, .02)):
            with self.subTest(k=k, adr=adr):
                a = arrays([(99, 100, 98, 99), (95, 105, 90, 104)], adr=adr)
                book, _, events = self.book(a, k)
                self.assertEqual(book[1][0][3], 104.)
                self.assertAlmostEqual(book[1][0][4], 104*(1-width))
                self.assertIsNone(book[1][0][6])
                self.assertIn('capped', [e['why'] for e in events])

    def test_ablation_keeps_the_wide_same_day_low(self):
        a = arrays([(99, 100, 98, 99), (95, 105, 90, 104)], adr=20)
        book, _, events = self.book(a, 'E6b')
        self.assertEqual(book[1][0][3:5], (104., 90.))
        self.assertNotIn('wide_stop', [e['why'] for e in events])

    def test_one_percent_floor_and_cap_below_one_percent_skips(self):
        a = arrays([(99, 100, 98, 99), (103, 105, 103.9, 104)], adr=20)
        for k in M.E6:
            with self.subTest(k=k):
                self.assertAlmostEqual(self.book(a, k)[0][1][0][4], 104*.99)
        a = arrays([(99, 100, 98, 99), (95, 105, 90, 104)], adr=1.6)  # ADR/2 = 0.8% < 1%
        for k in ('E6a', 'E6c', 'E6d'):
            with self.subTest(k=k):
                book, _, events = self.book(a, k)
                self.assertFalse(book[1])
                self.assertEqual(events[-1]['why'], 'wide_stop')

    def test_previous_close_adr_not_today(self):
        a = arrays([(99, 100, 98, 99), (95, 105, 90, 104)], adr=20)
        a['adr'][1] = 2  # today's ADR must not narrow the cap
        self.assertAlmostEqual(self.book(a, 'E6a')[0][1][0][4], 104*.95)

    def test_observation_windows(self):
        for k, when, expected in (('E6a', 3, 1), ('E6a', 4, 0), ('E6c', 5, 1), ('E6c', 6, 0)):
            with self.subTest(k=k, when=when):
                a = arrays([(99, 100, 98, 99)]*7, adr=10)
                a['open'][when], a['high'][when], a['low'][when], a['close'][when] = 99, 102, 99, 101
                self.assertEqual(sum(map(len, self.book(a, k)[0])), expected)

    def test_capped_entry_is_not_managed_on_entry_day_and_stops_next_day(self):
        a = arrays([(99, 100, 98, 99), (95, 105, 90, 104), (103, 104, 98, 100)], adr=20)
        book = self.book(a, 'E6a')[0]
        rules = M.execution_rules('E6a')
        _, _, trades = replay(a, book, rules, e9=[99, 95, 95])
        ex = trades[0]['executions']
        self.assertEqual([e['action'] for e in ex], ['entry', 'stop'])
        self.assertEqual(ex[1]['time'], a['days'][2])
        self.assertAlmostEqual(ex[1]['price'], 104*.95)

    def test_build_routes_each_candidate_with_e5_account_rules(self):
        for k in M.E6:
            with self.subTest(k=k):
                a = arrays([(99, 100, 98, 99), (95, 105, 90, 104), (104, 105, 103, 104)], adr=20)
                a['_ie47'] = dict(picks={str(a['days'][0]): ['SYN_00']}, pool=np.ones((3, 1), bool))
                book, rules, _, _ = M.IE47Study().build(a, {'candidate': k})
                self.assertEqual([len(x) for x in book], [0, 1, 0])
                self.assertEqual(rules, M.execution_rules('E5'))


if __name__ == '__main__':
    unittest.main()
