"""Timing of the STRONG pool: nothing a decision on day d reads may come from after its own moment."""
import unittest
from types import SimpleNamespace

import numpy as np

from studies.trader_replication.martin_strong import lag
from studies.trader_replication.martin_strong_scan import hold_sim, name_score, pool_book2, stage, tilt_core


def stub(n=60, m=12, seed=3):
    g = np.random.default_rng(seed)
    c = (100 * np.exp(np.cumsum(g.normal(0, .02, (n, m)), axis=0))).astype(np.float32)
    h, l, o = c * 1.02, c * .98, c * .995
    D = SimpleNamespace(c=c, h=h, l=l, o=o, U=np.ones((n, m), bool), adr=np.full((n, m), .06, dtype=np.float32), e9=c * .97)
    F = dict(a=c / np.roll(c, 1, axis=0), lowe9=(l / D.e9 - 1) / .06, cpos=(c - l) / (h - l), ext21=np.ones((n, m), dtype=np.float32))
    return D, F


def book(D, F):
    S = name_score(D, F, D.U, (('a',),))
    H = hold_sim(S, 3, 6)
    return S, H, pool_book2(D, F, H, S)


class Timing(unittest.TestCase):
    def test_lag_shifts_one_row(self):
        x = np.arange(6, dtype=np.float32).reshape(3, 2)
        self.assertTrue(np.isnan(lag(x)[0]).all())
        self.assertTrue((lag(x)[1:] == x[:-1]).all())

    def test_set_reads_only_the_evening_before(self):
        D, F = stub()
        _, H0, _ = book(D, F)
        F2 = dict(F)
        F2['a'] = F['a'].copy()
        F2['a'][40:] = np.random.default_rng(9).random(F['a'][40:].shape)
        _, H1, _ = book(D, F2)
        self.assertTrue((H0[:41] == H1[:41]).all())          # row 40 is scored from row 39

    def test_close_entry_reads_nothing_after_its_day(self):
        D, F = stub()
        _, _, b0 = book(D, F)
        D2, F2 = stub()
        for arr in (D2.c, D2.h, D2.l, D2.o):
            arr[41:] *= 1.5
        F2['lowe9'][41:] = -9
        F2['cpos'][41:] = 0
        F2['ext21'][41:] = 99
        _, _, b1 = book(D2, F2)
        self.assertEqual([x[:5] for r in b0[:41] for x in r], [x[:5] for r in b1[:41] for x in r])

    def test_stop_stays_below_the_fill_and_inside_his_range(self):
        D, F = stub()
        _, _, b = book(D, F)
        rows = [x for r in b for x in r]
        self.assertTrue(rows)
        for e in rows:
            self.assertLessEqual(e[4], e[3] * .99 + 1e-3)
            self.assertGreaterEqual(e[4], e[3] * .97 - 1e-3)      # half of a 6% ADR

    def test_stage_counts_from_five_days_before_to_ten_after(self):
        H = np.zeros((40, 2), bool)
        D = SimpleNamespace(his=[(20, 0, 'A', 'x', '2024-06-03'), (20, 1, 'B', 'x', '2026-06-03')])
        H[15, 0] = True                                      # five days before his buy counts
        H[31, 1] = True                                      # eleven days after does not
        self.assertEqual(stage(D, H), (1, 0))
        H[30, 1] = True
        self.assertEqual(stage(D, H), (1, 1))

    def test_tilt_keeps_strong_names_and_shorts(self):
        H = np.zeros((1, 3), bool)
        H[0, 0] = True
        strong, weak, short = ((1.0,), 0, 1, 10., 9., 'n1'), ((1.0,), 1, 1, 10., 9., 'n1'), ((0.0,), 2, -1, 10., 11., 'z')
        D = SimpleNamespace(reg=[[strong, weak, short]])
        row = tilt_core(D, H, .5)[0]
        self.assertEqual(row[0], strong)
        self.assertEqual(row[1][9], .5)
        self.assertEqual(row[2], short)
        self.assertEqual(len(tilt_core(D, H, 0)[0]), 2)


if __name__ == '__main__':
    unittest.main()
