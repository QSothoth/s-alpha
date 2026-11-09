"""The evening list reads bars up to t-1 only: changing day d's bars cannot move day d's ranks."""
import unittest

import numpy as np

from studies.trader_replication import ticket_t4 as T4


def arrays(n=60, m=5, seed=1):
    r = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(r.normal(0, .02, (n, m)), axis=0))
    return dict(close=c, high=c * 1.02, low=c * .98, open=c, turnover=c * 1e6 * (1 + np.arange(m)))


class Timing(unittest.TestCase):
    def test_today_does_not_move_todays_rank(self):
        a = arrays()
        b = {k: v.copy() for k, v in a.items()}
        for k in b:
            b[k][50:] = b[k][50:] * np.array([50, 1, 1, 1, .01])
        pool = np.ones(a['close'].shape, bool)
        np.testing.assert_array_equal(T4.ranks(a, pool)[:51], T4.ranks(b, pool)[:51])

    def test_the_pool_is_yesterdays(self):
        a = arrays()
        pool = np.ones(a['close'].shape, bool)
        pool[49, 4] = False
        self.assertEqual(T4.ranks(a, pool)[50, 4], 10 ** 6)


if __name__ == '__main__':
    unittest.main()
