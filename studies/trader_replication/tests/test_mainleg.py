import unittest

import numpy as np

from studies.trader_replication import mainleg


def series(n=40, entry=10, peak=20, base=100., top=200.):
    """Flat at `base`, a straight run from the entry to `top` at the peak, then a slide."""
    c = np.full(n, base)
    c[entry:peak + 1] = np.linspace(base, top, peak - entry + 1)
    c[peak + 1:] = top * .8
    return dict(o=c.copy(), h=c.copy(), l=c.copy(), c=c.copy())


class LegTests(unittest.TestCase):
    def test_reentries_and_duplicates_share_one_leg(self):
        p = {'US.X': series()}
        out = mainleg.legs([('US.X', 10, 'a'), ('US.X', 10, 'dup'), ('US.X', 14, 'b')], p)
        self.assertEqual(len(out), 1)
        self.assertEqual([e['index'] for e in out[0]['entries']], [10, 14])
        self.assertEqual(out[0]['peak'], 20)
        self.assertAlmostEqual(out[0]['entries'][0]['gain'], 1.0)

    def test_small_runs_are_not_big_winners(self):
        p = {'US.X': series(top=125.)}
        self.assertEqual(mainleg.legs([('US.X', 10, 'a')], p), [])

    def test_window_cut_by_data_end_is_marked(self):
        p = {'US.X': series(n=25)}
        self.assertTrue(mainleg.legs([('US.X', 10, 'a')], p)[0]['censored'])


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.p = {'US.X': series()}
        self.legs = mainleg.legs([('US.X', 10, 'a')], self.p)

    def run_buy(self, night, **kw):
        return mainleg.coverage({night: {'US.X'}}, self.legs, self.p, **kw)[0]

    def test_signal_night_fills_next_open(self):
        self.p['US.X']['o'][12] = 150.  # gap up on the fill day: room is measured from the open we pay
        row = self.run_buy(11)
        self.assertEqual(row['buys'][0]['fill'], 12)
        self.assertAlmostEqual(row['buys'][0]['share'], 200 / 150 - 1, places=3)
        self.assertFalse(row['covered'])  # the close of 120 would have left 67%; the open leaves 33%

    def test_earliest_fill_is_lead_sessions_before_his_entry(self):
        self.assertTrue(self.run_buy(6)['covered'])     # fills on 7 = entry - 3
        self.assertFalse(self.run_buy(5)['covered'])    # fills on 6: too early to count
        self.assertEqual(self.run_buy(6)['buy']['offset'], -3)

    def test_late_buy_needs_half_of_his_move_left(self):
        self.assertTrue(self.run_buy(12)['covered'])    # fills at 130: 54% left of his 100% run
        self.assertFalse(self.run_buy(13)['covered'])   # fills at 140: 43% left
        self.assertTrue(self.run_buy(13, keep=.4)['covered'])

    def test_buys_on_or_after_the_peak_day_do_not_count(self):
        self.assertEqual(self.run_buy(19)['buys'], [])  # fills on the peak day itself
        self.assertEqual(self.run_buy(21)['buys'], [])

    def test_synced_means_within_two_sessions_after_his_entry(self):
        self.assertTrue(self.run_buy(11)['synced'])     # fills on entry + 2
        row = self.run_buy(12)                          # fills on entry + 3: covered, not the same trade
        self.assertTrue(row['covered'])
        self.assertFalse(row['synced'])

    def test_held_needs_the_stop_untouched_through_the_peak(self):
        self.assertTrue(self.run_buy(9)['held'])
        self.p['US.X']['l'][15] = 100 * .96             # a 4% dip below a fill at 100 before the peak
        self.assertFalse(self.run_buy(9)['held'])
        self.assertTrue(self.run_buy(9, stop=.05)['held'])

    def test_unreachable_legs_stay_in_the_denominator(self):
        rows = mainleg.coverage({}, self.legs, self.p, pool={('US.Y', 12)})
        s = mainleg.summary(rows, ['2025'])['2025']
        self.assertEqual((s['n'], s['covered'], s['unreachable']), (1, 0, 1))


class OtherTests(unittest.TestCase):
    def test_entry_hits_window(self):
        out = mainleg.entry_hits({8: {'US.X'}, 30: {'US.Y'}}, [('US.X', 10, 'a'), ('US.Y', 10, 'b')])
        self.assertEqual(out, [True, False])

    def test_precision_counts_runs_from_the_fill_open(self):
        p = {'US.X': series(n=100), 'US.Y': series(n=100, top=120.)}
        out = mainleg.precision({9: {'US.X', 'US.Y'}}, p)
        self.assertEqual((out['n'], out['big']), (2, 1))


class ScorecardTests(unittest.TestCase):
    def test_windows_follow_the_coverage_rule(self):
        p = {'US.X': series()}
        legs = mainleg.legs([('US.X', 10, 'a')], p)
        self.assertEqual(mainleg.windows(legs, p), [[6, 7, 8, 9, 10, 11, 12]])  # fills 7..13 keep half the run

    def test_net_share_counts_distinct_names_over_the_window(self):
        pool = {(c, t) for c in 'ABCD' for t in range(5)}
        buys = {1: {'A'}, 2: {'A', 'B'}, 9: {'C'}}
        self.assertEqual(mainleg.net_share(buys, [[1, 3], []], pool), [0.5, None])

    def test_forward_run_from_the_fill_open(self):
        p = {'US.X': series(n=100)}
        out = mainleg.forward({9: {'US.X'}}, p)
        self.assertAlmostEqual(out['median'], 1.0)
        self.assertEqual((out['ge30'], out['ge100']), (1.0, 1.0))


if __name__ == '__main__':
    unittest.main()
