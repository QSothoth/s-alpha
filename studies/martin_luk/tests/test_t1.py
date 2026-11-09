"""Observable boundaries of T1's opt-in account attribution."""
import unittest

import numpy as np

from studies.martin_luk import t1_research as T
from studies.trader_replication import mainleg as M


class ThemeTests(unittest.TestCase):
    def test_peers_match_scalar_correlation_and_ignore_future_or_other_centers(self):
        rng = np.random.default_rng(13)
        returns = rng.normal(0, .01, (90, 5))
        returns[:, 1] = returns[:, 0]
        returns[:, 2] = -returns[:, 0]
        close = np.vstack([np.ones(5), np.cumprod(1+returns, axis=0)])*10
        pool, centers = np.arange(4), [0, 2]
        actual, _, _ = T.peer_groups(close, pool, 70, centers)
        corr = np.corrcoef((close[11:71]/close[10:70]-1).T)
        np.testing.assert_array_equal(actual[0], [j for j in pool if j != 0 and corr[0, j] >= .6])
        changed = close.copy()
        changed[71:] *= 100
        for other in (changed, close[:71]):
            peers, _, _ = T.peer_groups(other, pool, 70, centers[::-1])
            np.testing.assert_array_equal(peers[0], actual[0])
        self.assertIn(1, actual[0])
        self.assertNotIn(2, actual[0])
        peers, _, _ = T.peer_groups(close, np.array([0, 2]), 70, [0, 1])
        self.assertEqual(len(peers[0]), 0)
        self.assertEqual(len(peers[1]), 0)

    def test_incomplete_and_flat_returns_are_not_peers(self):
        x = 10*np.cumprod(1+.01*np.sin(np.arange(70)))
        close = np.column_stack([x, x, np.ones(70)*10, x])
        close[5, 1] = np.nan
        close[10, 3] = 0
        peers, usable, _ = T.peer_groups(close, np.arange(4), 60, [0, 1])
        np.testing.assert_array_equal(usable, [0])
        self.assertEqual(len(peers[0]), 0)
        self.assertEqual(len(peers[1]), 0)

    def test_industry_unknowns_never_form_a_group(self):
        labels = np.array(['芯片', '芯片', '未分类', '未分类', ''])
        np.testing.assert_array_equal(T.industry_peers(labels, np.arange(5), 0), [1])
        self.assertEqual(len(T.industry_peers(labels, np.arange(5), 2)), 0)
        self.assertEqual(len(T.industry_peers(labels, np.array([1]), 0)), 0)

    def fixture(self, code='X', entry=1, exit=7, open_=False):
        days = [f'2024-01-{i+2:02d}' for i in range(10)]
        close = np.array([10, 10, 12, 15, 18, 20, 17, 14, 13, 12.], float)
        prices = {code: dict(c=close)}
        pieces = M.lots([dict(index=entry, quantity=1., price=10., fee=.01),
                         dict(index=exit, quantity=-1., price=close[exit], fee=.02, open=open_)])
        trades = [dict(id=0, code=code, entry=entry, lots=pieces, closed=not open_, pnl=pieces[0]['pnl'])]
        legs = [dict(code=code, key='own', first=2, peak=4, top=18., gain=.8)]
        rows = M.attribute_lots(trades, legs, prices, days)
        return days, prices, trades, rows

    def test_default_does_not_change_y1_and_peer_cutoff_cannot_shorten_h(self):
        days, prices, trades, rows = self.fixture()
        self.assertIs(T.relabel(rows, prices), rows)
        original, _ = M.account_purity(rows, trades, days, prices, np.ones(10))
        relabeled = T.relabel(rows, prices, [3])
        actual, _ = M.account_purity(relabeled, trades, days, prices, np.ones(10))
        for k in ('H', 'gross', 'purity_gross', 'cap_equity', 'total_pnl'):
            self.assertAlmostEqual(original['2024'][k], actual['2024'][k])

    def test_broadening_keeps_fifo_pnl_costs_and_union_capital(self):
        days, prices, trades, rows = self.fixture()
        relabeled = T.relabel(rows, prices, [5])
        self.assertAlmostEqual(sum(r['pnl'] for r in relabeled), trades[0]['pnl'])
        self.assertAlmostEqual(sum(r['pnl'] for r in relabeled if r['strict_h']), rows[0]['h_pnl'])
        self.assertAlmostEqual(sum(r['pnl'] for r in relabeled if r['peer_h']), 2.)
        self.assertAlmostEqual(sum(r['pnl'] for r in relabeled if r['bucket'] == 'T1'), 9.99)
        original = M.capital_days(rows, days, prices)
        actual = M.capital_days(relabeled, days, prices)
        np.testing.assert_array_equal(original['gross'], actual['gross'])
        np.testing.assert_array_equal(actual['his'], [0, 10, 12, 15, 18, 20, 0, 0, 0, 0])
        self.assertAlmostEqual(actual['gross'][7], 0.)

    def test_public_small_segment_is_not_called_an_unseen_peer(self):
        days, prices, trades, rows = self.fixture()
        small = [dict(code='X', key='small', first=2, peak=4, top=18., gain=.8)]
        rows = M.attribute_lots(trades, [], prices, days, small)
        result = T.relabel(rows, prices, [5])
        self.assertAlmostEqual(sum(r['pnl'] for r in result if r['peer_h']), 9.99)
        self.assertAlmostEqual(sum(r['pnl'] for r in result if r['unseen_peer_h']), 2.)

    def test_terminal_mark_keeps_exposure_but_same_day_sale_does_not(self):
        days, prices, trades, rows = self.fixture(exit=5, open_=True)
        result = T.relabel(rows, prices, [5])
        self.assertEqual(M.capital_days(result, days, prices)['his'][5], 20.)
        days, prices, trades, rows = self.fixture(entry=2, exit=2)
        result = T.relabel(rows, prices, [2])
        self.assertEqual(M.capital_days(result, days, prices)['his'].sum(), 0.)

    def test_random_groups_match_size_reproduce_and_overlap_counts_once(self):
        record = {1: dict(usable=np.arange(6), known_industry=np.arange(6), groups=[
            dict(key='a', center=0, correlation=np.array([1, 2])),
            dict(key='b', center=3, correlation=np.array([1, 2]))])}
        legs = {'a': dict(first=2, peak=4), 'b': dict(first=2, peak=6)}
        rows = [dict(code=str(j), entry=1, exit=7) for j in range(6)]
        ci = {str(j): j for j in range(6)}
        self.assertEqual(T.peer_cutoffs(rows, record, legs, ci, 'correlation'), [-1, 6, 6, -1, -1, -1])
        one = {1: dict(record[1], groups=record[1]['groups'][:1])}
        first = T.peer_cutoffs(rows, one, legs, ci, 'correlation', repeat=2)
        self.assertEqual(first, T.peer_cutoffs(rows, one, legs, ci, 'correlation', repeat=2))
        self.assertEqual(sum(x >= 0 for x in first), 2)
        self.assertEqual(first[0], -1)
        sold = [dict(code='1', entry=1, exit=1)]
        self.assertEqual(T.peer_cutoffs(sold, record, legs, ci, 'correlation'), [-1])


if __name__ == '__main__':
    unittest.main()
