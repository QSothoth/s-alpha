import datetime as dt
import unittest

import numpy as np

from studies.trader_replication.martin_continue_du import _ROLL_MEAN
from studies.trader_replication.martin_continue_ee import fast_events
from studies.trader_replication.martin_continue_ht import turnover_books


class PriorFastStockPriorityTest(unittest.TestCase):
    def test_frequency_uses_prior_events_and_ignores_later_prices(self):
        days = [(dt.date(2024, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(260)]
        index = np.arange(len(days))
        slow = np.full(len(days), 100.)
        fast = np.array([106. if i % 2 else 100. for i in index])
        row = [((2., 1., float(j)), j, 1, 10., 9., 'list') for j in range(2)]
        book = [[] for _ in days]
        book[259] = row

        def ranked(fast_prices):
            events = np.column_stack([fast_events(days, values, [], index) for values in (slow, fast_prices)])
            frequency = _ROLL_MEAN(events.astype(np.float32), 250)
            ordered, _ = turnover_books(book, [259], frequency, np.array(['A', 'B']))
            return [e[1] for e in sorted(ordered[259], key=lambda e: e[0])]

        changed = fast.copy()
        changed[259] = 1.
        self.assertEqual(ranked(fast), [1, 0])
        self.assertEqual(ranked(changed), [1, 0])


if __name__ == '__main__':
    unittest.main()
