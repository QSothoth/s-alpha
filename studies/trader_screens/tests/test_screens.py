"""Draft screens: no look-ahead, and each setup fires on the day its rule says on hand-made paths."""
import unittest

import numpy as np

from studies.trader_screens import screens as S

T0 = np.datetime64('2025-01-01')


def panel(close, vol=None, high=None, low=None, open_=None, turnover=1e8):
    c = np.asarray(close, float)
    if c.ndim == 1:
        c = c[:, None]
    h = c * 1.01 if high is None else np.asarray(high, float).reshape(c.shape)
    l = c * .99 if low is None else np.asarray(low, float).reshape(c.shape)
    o = np.vstack([c[:1], c[:-1]]) if open_ is None else np.asarray(open_, float).reshape(c.shape)
    v = np.full(c.shape, 1e6) if vol is None else np.asarray(vol, float).reshape(c.shape)
    n = len(c)
    return dict(days=np.array([str(T0 + i) for i in range(n)]), codes=np.array([f'US.S{j}' for j in range(c.shape[1])]),
                open=o, high=h, low=l, close=c, volume=v, turnover=np.full(c.shape, turnover), raw_close=c)


def random_panel(n=360, k=40, seed=0):
    rng = np.random.default_rng(seed)
    drift = rng.normal(.0015, .002, k)
    r = rng.normal(drift, .03, (n, k))
    c = 20 * np.exp(np.cumsum(r, axis=0))
    spread = np.abs(rng.normal(.02, .01, (n, k))) + .005
    o = c * np.exp(rng.normal(0, .01, (n, k)))
    h = np.fmax(o, c) * (1 + spread)
    l = np.fmin(o, c) * (1 - spread)
    v = rng.lognormal(14, .5, (n, k))
    p = panel(c, v, h, l, o)
    p['turnover'] = v * c
    return p


def cut(p, n):
    return {k: (v[:n] if isinstance(v, np.ndarray) and len(v) == len(p['days']) else v) for k, v in p.items()}


class NoLookAheadTests(unittest.TestCase):
    def test_every_draft_on_day_t_ignores_later_bars(self):
        p = random_panel()
        full = {s.id: s.run(S.Feat(p, 'us')) for s in S.DRAFTS}
        fired = 0
        for n in (300, 330, 359):
            for s in S.DRAFTS:
                short = s.run(S.Feat(cut(p, n), 'us'))
                a, b = full[s.id], short
                np.testing.assert_array_equal(a['watch'][n - 1], b['watch'][n - 1], err_msg=s.id)
                for x, y in zip(a['setups'], b['setups']):
                    np.testing.assert_array_equal(x.mask[n - 1], y.mask[n - 1], err_msg=f'{s.id} {x.name}')
                    np.testing.assert_array_equal(x.price[n - 1], y.price[n - 1], err_msg=f'{s.id} {x.name}')
                    np.testing.assert_array_equal(x.stop[n - 1], y.stop[n - 1], err_msg=f'{s.id} {x.name}')
                    for t in x.tags:
                        np.testing.assert_array_equal(x.tags[t][n - 1], y.tags[t][n - 1])
                    fired += int(x.mask[n - 1].sum())
        self.assertGreater(fired, 0)              # the comparison is not vacuous


class HelperTests(unittest.TestCase):
    def test_rolling_max_needs_a_full_window(self):
        x = np.array([[1.], [3.], [np.nan], [2.], [5.], [4.]])
        got = S.rolling(x, 2, 'max')[:, 0]
        np.testing.assert_array_equal(got, [np.nan, 3, np.nan, np.nan, 5, 5])
        np.testing.assert_array_equal(S.rolling(x, 2, 'mean')[:, 0], [np.nan, 2, np.nan, np.nan, 3.5, 4.5])

    def test_triggered_needs_yesterdays_ready_and_a_break_of_its_level(self):
        p = panel([10, 10, 10, 10], high=[10, 10.5, 11.2, 12], open_=[10, 10, 11.1, 11.5])
        F = S.Feat(p, 'us')
        ready = np.array([[False], [True], [True], [False]])
        level = np.array([[9.], [10.8], [11.0], [99.]])
        m, entry = S.triggered_from(F, ready, level)
        self.assertEqual(m[:, 0].tolist(), [False, False, True, True])
        self.assertAlmostEqual(entry[2, 0], 11.1)      # opened above 10.8: the open
        self.assertAlmostEqual(entry[3, 0], 11.5)      # level 11.0 < open 11.5


class SetupTests(unittest.TestCase):
    def test_episodic_pivot_is_the_gap_and_volume_day(self):
        n = 80
        c = np.full(n, 20.0)
        o = c.copy()
        v = np.full(n, 1e6)
        c[60:] = 23.0
        o[60] = 22.5                                   # +12.5% gap on 4x volume
        v[60] = 4e6
        p = panel(c, v, high=np.fmax(o, c) * 1.01, low=np.fmin(o, c) * .99, open_=o)
        ep = next(s for s in S.Qullamaggie().run(S.Feat(p, 'us'))['setups'] if s.name == 'EP')
        self.assertEqual(np.flatnonzero(ep.mask[:, 0]).tolist(), [60])
        self.assertAlmostEqual(ep.price[60, 0], 22.5)

    def test_new_high_breakout_needs_a_ten_day_base(self):
        n = 300
        run_up = 10 * 1.005 ** np.arange(n)                             # a new high every day
        based = run_up.copy()
        based[280:295] = based[279]                                     # 15 flat days
        based[295:] = based[279] * 1.05                                 # then the break
        c = np.stack([run_up, based], 1)
        p = panel(c, high=c * 1.03, low=c * .99)                        # ADR about 4%
        trig = next(s for s in S.ChristianFlanders().run(S.Feat(p, 'us'))['setups'] if s.kind == 'triggered')
        self.assertFalse(trig.mask[260:, 0].any())
        self.assertEqual(np.flatnonzero(trig.mask[260:, 1]).tolist(), [295 - 260])

    def test_trend_template_holds_in_an_uptrend_only(self):
        n = 300
        up = 10 * 1.004 ** np.arange(n)
        down = 10 * .997 ** np.arange(n)
        cols = [up, down] + [10 * (1 + .0001 * k) ** np.arange(n) for k in range(25)]
        F = S.Feat(panel(np.stack(cols, 1)), 'us')
        w = S.MarkMinervini().run(F)['watch']
        self.assertTrue(w[-1, 0])
        self.assertFalse(w[-1, 1])

    def test_ema_crossback_is_the_first_held_pullback_after_a_wedge_pop(self):
        n = 120
        c = np.r_[np.full(80, 20.0), [19.6, 19.5, 19.6, 19.5, 19.6], [20.6, 21.0, 21.4, 21.8, 22.2],
                  [21.9, 22.4, 22.8, 22.0, 22.9], np.full(25, 23.5)]
        h, l = c * 1.06, c * .995                     # ADR about 6.5%, lows hug the close
        l[93] = 21.3                                   # day 93 dips to the 10 EMA and closes above the 20 EMA
        l[98] = 21.0                                   # a second dip is not the first pullback
        out = S.OliverKell().run(S.Feat(panel(c, high=h, low=l), 'us'))
        pop = next(s for s in out['setups'] if s.name == 'Wedge Pop')
        cross = next(s for s in out['setups'] if s.name == 'EMA Crossback')
        self.assertIn(85, np.flatnonzero(pop.mask[:, 0]).tolist())
        self.assertEqual(np.flatnonzero(cross.mask[:, 0]).tolist(), [93])


if __name__ == '__main__':
    unittest.main()
