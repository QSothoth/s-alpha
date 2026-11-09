import unittest

import numpy as np

from studies.trader_replication import system
from studies.trader_replication.martin_continue_bz import partial_list


class PartialListTests(unittest.TestCase):
    def test_only_list_trims_15_percent_of_initial_size_at_3r_and_5r(self):
        dates = np.array(['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05'])
        close = np.array([[100., 100.], [120., 120.], [140., 140.], [140., 140.]])
        op = np.array([[100., 100.], [101., 101.], [121., 121.], [140., 140.]])
        high = np.array([[100., 100.], [132., 132.], [151., 151.], [141., 141.]])
        low = np.array([[100., 100.], [100., 100.], [110., 110.], [139., 139.]])
        px = dict(open=op, high=high, low=low, close=close, dates=dates, codes=np.array(['LIST', 'CORE']))
        entries = [[(0., 0, 1, 100., 90., 'list'), (1., 1, 1, 100., 90., 'n1')], [], [], []]
        base = system.Rules(trims=(10,), trim_frac=.3, trail='', buy_cost=0, sell_cost=0,
                            max_gross=2., max_position=.5, risk=.1)
        changed = partial_list(base)
        trades = {t['code']: t for t in system.simulate(px, {}, changed, entries, dates[0], dates[-1], audit=True)[2]}
        actions = trades['LIST']['executions']
        trims = [e for e in actions if e['action'] == 'trim']
        self.assertEqual([e['price'] for e in trims], [130., 150.])
        self.assertTrue(all(abs(e['shares'] - actions[0]['shares'] * .15) < 1e-12 for e in trims))
        self.assertFalse(any(e['action'] == 'trim' for e in trades['CORE']['executions']))


if __name__ == '__main__':
    unittest.main()
