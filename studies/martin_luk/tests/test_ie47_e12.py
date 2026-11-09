"""E12 watch list and setups: day t never reads t+1; list entry and exit; one breakout by hand; nightly cap."""
import unittest

import numpy as np

from studies.martin_luk import e12_research as E12


def panel(closes, columns=1, adr=6.):
    c = np.repeat(np.asarray(closes, float)[:, None], columns, axis=1)
    return dict(open=c*.995, high=c*1.01, low=c*.99, close=c.copy(), adr=np.full(c.shape, adr))


class NoLookaheadTests(unittest.TestCase):
    def test_future_rows_never_change_today(self):
        rng = np.random.default_rng(3)
        T, N = 90, 8
        c = 50*np.exp(np.cumsum(rng.normal(.004, .04, (T, N)), axis=0))
        o = c*np.exp(rng.normal(0, .02, (T, N)))
        P = dict(open=o, high=np.maximum(o, c)*(1+rng.uniform(0, .04, (T, N))),
                 low=np.minimum(o, c)*(1-rng.uniform(0, .04, (T, N))), close=c, adr=rng.uniform(3, 9, (T, N)))
        pool, scope = rng.random((T, N)) < .4, rng.random((T, N)) < .8
        before = E12.setups(P, pool, scope, flag=True)
        t0 = 60
        Q = {k: v.copy() for k, v in P.items()}
        for k in ('open', 'high', 'low', 'close'):
            Q[k][t0+1:] *= 3
        pool2, scope2 = pool.copy(), scope.copy()
        pool2[t0+1:], scope2[t0+1:] = ~pool[t0+1:], ~scope[t0+1:]
        after = E12.setups(Q, pool2, scope2, flag=True)
        for k in before:
            np.testing.assert_array_equal(before[k][:t0+1], after[k][:t0+1], err_msg=k)
        self.assertTrue(any(before[k].any() for k in ('D0', 'D1a', 'D1c', 'PB', 'EP')))


class WatchListTests(unittest.TestCase):
    def test_enters_on_the_pool_session_and_leaves_after_three_closes_below_the_50_ema(self):
        close = np.r_[np.linspace(100, 120, 60), [119, 118.5, 118, 117.5, 117]][:, None]   # above the 20-day low
        pool = np.zeros(close.shape, bool)
        pool[55] = True
        e50 = np.full(close.shape, 100.)
        e50[60:] = 125.
        wl = E12.watch_list(pool, close, e50)
        self.assertFalse(wl[54, 0])
        self.assertTrue(wl[55:63, 0].all())       # closes below 50 EMA on 60, 61, 62: judged at 62's close
        self.assertFalse(wl[63:, 0].any())


class BreakoutTests(unittest.TestCase):
    def test_inside_day_then_close_above_its_high_fires_d1a(self):
        closes = list(100*1.004**np.arange(70))
        P = panel(closes)
        t = 69
        P['high'][t-1], P['low'][t-1] = P['high'][t-2]*.999, P['low'][t-2]*1.001       # inside day
        P['close'][t-1] = (P['high'][t-1]+P['low'][t-1])/2
        P['open'][t], P['low'][t], P['high'][t] = P['close'][t-1], P['close'][t-1]*.995, P['high'][t-1]*1.03
        P['close'][t] = P['high'][t]*.995
        pool = np.zeros(P['close'].shape, bool)
        pool[40] = True
        sig = E12.setups(P, pool, np.ones(P['close'].shape, bool))
        self.assertTrue(sig['D1a'][t, 0])
        P['close'][t] = P['high'][t-1]*.999                                                 # closes under the high
        self.assertFalse(E12.setups(P, pool, np.ones(P['close'].shape, bool))['D1a'][t, 0])


class BookTests(unittest.TestCase):
    def test_at_most_five_a_night_by_setup_then_turnover_at_that_close(self):
        T, N = 3, 7
        c = np.full((T, N), 100.)
        A = dict(days=np.array(['2025-01-02', '2025-01-03', '2025-01-06']), codes=np.array([f'S{j}' for j in range(N)]),
                 close=c, low=c*.98, adr=np.full((T, N), 8.), to20=np.tile(np.arange(N, dtype=float), (T, 1)))
        sig = {k: np.zeros((T, N), bool) for k in ('D1a', 'EP', 'PB', 'D1b', 'D1c', 'wl')}
        sig['PB'][2] = True
        sig['EP'][2, 1] = True
        entries = E12.book(A, sig, E12.SPEC['C4'], None)
        got = entries[2]
        self.assertEqual(len(got), 5)
        self.assertEqual([e[1] for e in got], [1, 6, 5, 4, 3])
        self.assertEqual(got[0][5], 'e12_EP')
        self.assertEqual((got[0][3], got[0][4]), (100., 98.))
        self.assertEqual(entries[1], [])


if __name__ == '__main__':
    unittest.main()
