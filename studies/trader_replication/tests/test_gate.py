"""The engineering gate on synthetic panels: a system that reads tomorrow's bar fails the look-ahead check, a causal
one passes; fills outside the day's range and win rates above the limit are caught."""
import unittest

import numpy as np

from studies.trader_replication import gate as G, study as S, system as Y


def panel(n=300, k=6, seed=3):
    rng = np.random.default_rng(seed)
    c = 50 * np.exp(np.cumsum(rng.normal(0, .02, (n, k)), axis=0))
    o = c * (1 + rng.normal(0, .005, (n, k)))
    h, l = np.fmax(o, c) * 1.01, np.fmin(o, c) * .99
    days = np.array([str(np.datetime64('2024-01-01') + i) for i in range(n)])
    return dict(days=days, codes=np.array([f'US.T{j}' for j in range(k)]), market='us', open=o, high=h, low=l,
                close=c)


class Toy(S.Study):
    """Buys the close when the close rose (causal) or when tomorrow's close will rise ('entry' leak); the other
    leaks keep causal signals but let the panel's length change what the engine consumes."""
    def __init__(self, leak):
        self.full_panel, self.leak = panel(), leak

    def arrays(self, market, upto=None):
        P = self.full_panel
        k = len(P['days']) if upto is None else int(np.searchsorted(P['days'], upto, side='right'))
        return {key: (v[:k] if key not in ('codes', 'market') else v) for key, v in P.items()}

    def build(self, A, cfg, trace=None):
        c, l = A['close'], A['low']
        sig = np.zeros(c.shape, bool)
        if self.leak == 'entry':
            sig[:-1] = c[1:] > c[:-1]
        else:
            sig[1:] = c[1:] > c[:-1]
        n = len(c)
        extra = (None, .05 if n > 200 else .02) if self.leak == 'size' else ()
        entries = [[(0.0, int(j), 1, float(c[d, j]), float(l[d, j] * .99), 'x') + extra for j in np.flatnonzero(sig[d])]
                   for d in range(n)]
        if self.leak == 'order' and n > 200:
            entries = [lst[::-1] for lst in entries]          # same priority, another order
        rules = Y.Rules(trail='', risk=.006 if self.leak == 'rules' and n > 200 else .005)
        return entries, rules, sig, np.ones(c.shape, bool)


class GateTests(unittest.TestCase):
    cuts = ('2024-04-15', '2024-07-01')

    def test_causal_system_passes_lookahead(self):
        self.assertTrue(G.check_lookahead(Toy(None), {}, 'us', cuts=self.cuts)['ok'])

    def test_leaking_system_fails_lookahead(self):
        res = G.check_lookahead(Toy('entry'), {}, 'us', cuts=self.cuts)
        self.assertFalse(res['ok'])
        self.assertTrue(any('entries differ' in d for c in res['cuts'] for d in c['diff']))

    def test_leaks_into_rules_sizing_and_order_fail(self):
        for leak, word in (('rules', 'rules differ'), ('size', 'entries differ'), ('order', 'entries differ')):
            res = G.check_lookahead(Toy(leak), {}, 'us', cuts=self.cuts)
            self.assertFalse(res['ok'], leak)
            self.assertTrue(any(word in d for c in res['cuts'] for d in c['diff']), leak)

    def test_fills_inside_the_day_pass_outside_fail(self):
        A = panel()
        d, j = 10, 2
        day = str(A['days'][d])
        good = [dict(code='US.T2', executions=[dict(time=day, action='entry', price=float(A['close'][d, j]))])]
        bad = [dict(code='US.T2', executions=[dict(time=day, action='stop', price=float(A['low'][d, j] * .9))])]
        self.assertTrue(G.check_fills(A, good)['ok'])
        self.assertFalse(G.check_fills(A, bad)['ok'])
        self.assertFalse(G.check_fills(A, [dict(code='US.T2')])['ok'])          # no audit record
        self.assertFalse(G.check_fills(A, [])['ok'])                           # nothing executed at all

    def test_engine_trades_have_fills_inside_the_day(self):
        st = Toy(None)
        A = st.arrays('us')
        entries, rules, mask, pool = st.build(A, {})
        px = dict(open=A['open'], high=A['high'], low=A['low'], close=A['close'], dates=A['days'], codes=A['codes'])
        _, _, tr = Y.simulate(px, {}, rules, entries, A['days'][0], A['days'][-1], audit=True)
        self.assertTrue(tr)
        self.assertTrue(G.check_fills(A, tr)['ok'])

    def test_win_rate_limit(self):
        trades = lambda w, n=100: [dict(ret=.1, why='trail')] * w + [dict(ret=-.02, why='stop')] * (n - w)
        self.assertTrue(G.check_win(trades(35))['ok'])
        self.assertFalse(G.check_win(trades(36))['ok'])
        few = G.check_win(trades(20, 25))
        self.assertTrue(few['ok'])
        self.assertEqual(few['status'], 'unchecked')
        self.assertFalse(G.check_win([dict(ret=float('nan'), why='stop')] * 30)['ok'])
        # positions still open at the window's end are not closed trades
        self.assertTrue(G.check_win(trades(35) + [dict(ret=.5, why='end')] * 10)['ok'])

    def test_data_check(self):
        w = ('2024-01-02', '2026-10-16')
        days = np.array(['2023-12-29', '2024-01-02', '2026-10-16'])
        span = ['2024-01-02', '2026-10-16']
        self.assertTrue(G.check_data('v1', 'f', span, 'v1', 'f', w, days)['ok'])
        self.assertFalse(G.check_data('v0', 'f', span, 'v1', 'f', w, days)['ok'])
        self.assertFalse(G.check_data('v1', 'g', span, 'v1', 'f', w, days)['ok'])
        self.assertFalse(G.check_data('v1', 'f', span, 'v1', None, w, days)['ok'])        # nothing pinned
        self.assertFalse(G.check_data('v1', 'f', ['2023-12-29', span[1]], 'v1', 'f', w, days)['ok'])


class MetricTests(unittest.TestCase):
    def test_definitions(self):
        from studies.trader_replication import compare as C
        days = np.array(['2024-01-02', '2024-01-03', '2024-12-31'])
        curve = np.array([.9, .8, 1.2])
        tr = [dict(entry='2024-01-02', exit='2024-01-03', why='stop', ret=-.05, pnl=-.10, days=1, risk_pct=.03),
              dict(entry='2024-01-02', exit='2024-12-31', why='trail', ret=.40, pnl=.30, days=200, risk_pct=.02),
              dict(entry='2024-01-03', exit='2024-12-31', why='end', ret=.10, pnl=.10, days=199, risk_pct=.04)]
        m = C.metrics(curve, days, tr, [[], [], []], 0, 3)
        self.assertAlmostEqual(m['maxdd'], .2)                       # from the starting equity 1, not from .9
        self.assertEqual((m['trades'], m['open_at_end']), (2, 1))
        self.assertEqual(m['win'], .5)
        self.assertAlmostEqual(m['payoff'], 8.0)
        self.assertAlmostEqual(m['pnl_top10'], .30 / .40)            # by money, open positions valued
        self.assertAlmostEqual(m['open_mean'], (2 + 2 + 1) / 3)     # the open position counts on the last close
        self.assertAlmostEqual(m['cagr'], 1.2 ** (365.25 / 364) - 1)


if __name__ == '__main__':
    unittest.main()
