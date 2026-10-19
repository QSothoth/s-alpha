"""Flanders' short side on synthetic panels: the 200-day limit is armed on the previous day's data and filled only
when the day trades up to the line; the earnings-gap short is sold at the open of a 10% gap under a falling 200-day
that rejected a rally; and nothing reads later bars."""
import unittest

import numpy as np

from studies.christian_flanders import replicate as R
from studies.christian_flanders.tests.test_entries import panel as panel0
from studies.trader_replication import shorts as SH


def panel(rows):
    A = panel0(rows)
    A['to20'], A['adr'] = A['F'].to20, A['F'].adr
    return A


def falling(n=260):
    c = np.linspace(30, 12, n)
    return [(x * 1.002, x * 1.02, x * .98, x) for x in c]


class FlandersShortTests(unittest.TestCase):
    def test_r200_level_is_yesterdays_200_day(self):
        rows = falling()
        A = panel(rows)
        z = R.STUDY.short_setups(A, {'setups': ['r200']})[0]['r200']
        s200 = A['F'].sma(200)[:, 0]
        self.assertTrue(z['armed'][250, 0])
        self.assertAlmostEqual(z['level'][250, 0], s200[249])
        e = SH.short_entries(A, {'r200': z}, {})
        self.assertEqual([x for x in e[250] if x[1] == 0], [])         # the day never got near the line

    def test_gap_short_after_a_rejection(self):
        rows = falling()
        s200 = panel(rows)['F'].sma(200)[:, 0]
        k = 230                                                         # a rally that tags the line, closes under
        o, h, l, c = rows[k]
        rows[k] = (o, s200[k] * 1.01, l, c)
        last = rows[-1][3]
        rows.append((last * .88, last * .89, last * .85, last * .86))   # gaps 12% down
        A = panel(rows)
        z = R.STUDY.short_setups(A, {'setups': ['gap200']})[0]['gap200']
        self.assertEqual(list(np.flatnonzero(z['armed'][:, 0])), [len(rows) - 1])
        (e,) = [x for x in SH.short_entries(A, {'gap200': z}, {'stop_w': .03})[len(rows) - 1] if x[1] == 0]
        self.assertAlmostEqual(e[3], last * .88)                        # sold at the open
        self.assertAlmostEqual(e[4], last * .88 * 1.03)
        self.assertIsNone(e[6])                                         # the high 0.89 never reached the stop
        z3 = R.STUDY.short_setups(A, {'setups': ['gap200'], 'gap_stop': 'sma150'})[0]['gap200']
        (e,) = [x for x in SH.short_entries(A, {'gap200': z3}, {})[len(rows) - 1] if x[1] == 0]
        self.assertAlmostEqual(e[4], A['F'].sma(150)[-2, 0] * 1.01)      # yesterday's 150-day, plus 1%
        A2 = panel(rows[:k] + [rows[k - 1]] + rows[k + 1:])             # without the rejected rally: no short
        z2 = R.STUDY.short_setups(A2, {'setups': ['gap200']})[0]['gap200']
        self.assertFalse(z2['armed'][-1, 0])

    def test_no_later_bars_are_read(self):
        rng = np.random.default_rng(11)
        c = 30 * np.exp(np.cumsum(rng.normal(-.002, .03, 330)))
        rows = [(x * (1 + rng.normal(0, .03)), x * 1.04, x * .96, x) for x in c]
        rows = [(min(max(o, l), h), h, l, x) for (o, h, l, x) in rows]
        full = R.STUDY.short_setups(panel(rows), {})[0]
        cut = 280
        part = R.STUDY.short_setups(panel(rows[:cut + 1]), {})[0]
        for k in full:
            for f in ('armed', 'level'):
                if f in full[k]:
                    np.testing.assert_array_equal(full[k][f][:cut + 1], part[k][f])


if __name__ == '__main__':
    unittest.main()
