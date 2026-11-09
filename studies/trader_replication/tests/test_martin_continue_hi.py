import unittest

import numpy as np

from studies.trader_replication.system import Rules, simulate


class PreopenTrialLimitTest(unittest.TestCase):
    def test_unfilled_trial_does_not_free_same_day_reserved_slot(self):
        days = np.array(['2025-01-01', '2025-01-02', '2025-01-03'])
        opens = np.array([[10., 10.], [11., 10.], [10., 10.]])
        px = {'dates': days, 'codes': np.array(['US.A', 'US.B']), 'open': opens,
              'high': np.maximum(opens, 11.), 'low': np.full((3, 2), 10.),
              'close': np.full((3, 2), 10.)}
        first = ((0,), 0, 1, 11., 9., 'list', None)
        second = ((1,), 1, 1, 10., 9., 'list', None)
        rules = Rules(trail='', trims=(), risk=.01, max_gross=1., max_position=1., gross_cost=True,
                      max_open_by_kind={'list': 1}, intraday_kinds=('list',),
                      buy_cost=0., sell_cost=0., margin_rate=0.)
        track = {}
        _, _, trades = simulate(px, {}, rules, [[], [first, second], [second]], days[1], days[2],
                                audit=True, track=track, preopen=True)
        self.assertEqual(track['preopen_plans'][0]['orders'][0]['execution'], 'limit_expired')
        self.assertEqual(track['preopen_plans'][0]['orders'][1]['reason'], 'kind_position_limit')
        self.assertEqual([(t['code'], t['entry']) for t in trades], [('US.B', '2025-01-03')])


if __name__ == '__main__':
    unittest.main()
