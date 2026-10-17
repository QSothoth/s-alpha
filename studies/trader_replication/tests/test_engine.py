"""Ledger checks, fidelity recall / random baseline and same-day edge on tiny synthetic panels."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from studies.trader_replication import edge as E, fidelity as F, ledger as L

HEAD = 'id,ticker,side,entry_date,window_lo,window_hi,precision,setup,trigger,stop_pct,outcome,r_multiple,source,note\n'


def write(rows):
    path = Path(tempfile.mkdtemp()) / 'trades.csv'
    path.write_text(HEAD + ''.join(r + '\n' for r in rows), encoding='utf-8')
    return path


class LedgerTests(unittest.TestCase):
    def test_load_and_split(self):
        p = write(['A1,aaa,long,2025-01-03,2025-01-03,2025-01-03,exact,ep,orh,2,win,5,v@1,',
                   'A2,BBB,short,,2025-03-01,2025-03-31,window,short_pullback,,,loss,,v@2,'])
        t = L.load(p)
        self.assertEqual(t[0].ticker, 'AAA')
        self.assertTrue(t[0].dated)
        self.assertFalse(t[1].dated)
        sel, val = L.split(t, '2025-02-01')
        self.assertEqual([x.id for x in sel], ['A1'])
        self.assertEqual([x.id for x in val], ['A2'])

    def test_rejects_bad_rows(self):
        for row in ('A1,AAA,long,2025-01-03,2025-01-02,2025-01-03,exact,ep,,,win,,v,',     # exact needs one day
                    'A1,AAA,flat,2025-01-03,2025-01-03,2025-01-03,exact,ep,,,win,,v,',
                    'A1,AAA,long,2025-01-09,2025-01-02,2025-01-05,chart,ep,,,win,,v,'):  # date outside window
            with self.assertRaises(ValueError):
                L.load(write([row]))
        with self.assertRaises(ValueError):
            L.load(write(['A1,AAA,long,,2025-01-02,2025-01-05,window,ep,,,win,,v,'] * 2))


class FidelityTests(unittest.TestCase):
    def setUp(self):
        self.days = np.array(['2025-01-0%d' % i for i in range(1, 6)])
        self.codes = np.array(['US.AAA', 'US.BBB', 'US.CCC', 'US.DDD'])
        self.trades = L.load(write(['A1,AAA,long,2025-01-03,2025-01-03,2025-01-03,exact,ep,,,win,,v,',
                                    'A2,BBB,long,2025-01-03,2025-01-02,2025-01-04,chart,ep,,,win,,v,',
                                    'A3,ZZZ,long,2025-01-03,2025-01-03,2025-01-03,exact,ep,,,win,,v,']))

    def test_hits_use_the_window_and_skip_unknown_names(self):
        loc, missing = F.locate(self.trades, self.days, self.codes)
        self.assertEqual(missing, ['A3'])
        m = np.zeros((5, 4), bool)
        m[1, 1] = True                    # BBB flagged on 01-02, inside its window
        m[3, 0] = True                    # AAA flagged on 01-04, after its one-day window
        r = F.recall(m, loc)
        self.assertEqual(r['per_trade'], {'A1': False, 'A2': True})
        self.assertAlmostEqual(r['recall'], .5)

    def test_random_baseline_matches_list_width(self):
        loc, _ = F.locate(self.trades, self.days, self.codes)
        m = np.zeros((5, 4), bool)
        m[:, 0] = True                    # one of four names every day
        r = F.recall(m, loc)
        exact, three_days = .25, 1 - .75 ** 3
        self.assertAlmostEqual(r['random'], (exact + three_days) / 2)
        self.assertAlmostEqual(r['lift'], .5 / r['random'])

    def test_funnel_is_cumulative(self):
        loc, _ = F.locate(self.trades, self.days, self.codes)
        a = np.ones((5, 4), bool)
        b = np.zeros((5, 4), bool)
        b[2, 0] = True
        rows = F.funnel([('all', a), ('only AAA on 01-03', b)], loc)
        self.assertEqual([r['hits'] for r in rows], [2, 1])
        self.assertEqual(rows[1]['lost'], ['A2'])


class EdgeTests(unittest.TestCase):
    def test_excess_compares_within_day_and_group(self):
        out = np.array([[.10, .00, .30, .20], [.05, .05, .00, .00]])
        grp = np.array([[0, 0, 1, 1], [0, 0, 1, 1]], np.int8)
        ev = np.ones((2, 4), bool)
        flag = np.array([[1, 0, 0, 1], [0, 0, 0, 0]], bool)
        res = E.excess(out, grp, ev, flag, np.array([True, True]))
        self.assertEqual(res['days'], 1)                        # day 2 has no flagged event
        self.assertAlmostEqual(res['excess'], ((.10 - .00) + (.20 - .30)) / 2)
        self.assertAlmostEqual(res['inside'], .15)

    def test_forward_starts_at_next_open(self):
        c = np.array([[10.], [11.], [12.], [13.]])
        o = np.array([[9.], [10.], [11.], [12.]])
        f = E.forward(c, o, horizon=2)
        self.assertAlmostEqual(f[0, 0], 12 / 10 - 1)
        self.assertTrue(np.isnan(f[2, 0]))


if __name__ == '__main__':
    unittest.main()
