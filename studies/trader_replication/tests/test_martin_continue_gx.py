import unittest

import numpy as np

from studies.trader_replication import shorts
from studies.trader_replication.martin_continue_dp import opening_fill
from studies.trader_replication.system import Rules, simulate


class OpeningShortTest(unittest.TestCase):
    def test_only_preselected_marketable_open_is_available_at_open(self):
        for high in (10.5, 11.5):
            status, fill, stop, exit_price = opening_fill(10.5, high, 10., .05, True)
            self.assertEqual((status, fill), ('marketable_open', 10.5))
            self.assertEqual(exit_price, stop if high >= stop else None)
        self.assertEqual(opening_fill(9., 11., 10., .05, True)[0], 'intraday_limit')

    def test_opening_short_cannot_displace_a_long_that_stops_later(self):
        days = np.array(['2025-01-02'])
        opening = np.array([[10., 10.]])
        px = {'dates': days, 'codes': np.array(['US.LONG', 'US.SHORT']), 'open': opening,
              'high': np.array([[10., 11.]]), 'low': np.array([[9., 10.]]), 'close': opening}
        long = ((1., 0), 0, 1, 10., 9., 'n1', 9.)
        short = ((1., -100), 1, -1, 10., 11., 's_Z15', 11.)
        book = shorts.combine([[long]], [[short]])
        rules = Rules(trail='', trims=(), intraday_kinds=('n1', 's_Z15'), max_open=1,
                      buy_cost=0, sell_cost=0, margin_rate=0)
        _, _, trades = simulate(px, {}, rules, book, days[0], days[-1], audit=True)
        self.assertEqual([(t['code'], t['why']) for t in trades], [('US.LONG', 'stop_day0')])


if __name__ == '__main__':
    unittest.main()
