"""The runner on a synthetic study: the open positions' exit levels it reports are the engine's own (one more day
through the stop exits there), the session's buys and sells, and the freeze-day split."""
import unittest
from types import SimpleNamespace

import numpy as np

from studies.trader_replication import runner as RN, study as S, system as Y


def panel(n=80, k=3, seed=5):
    rng = np.random.default_rng(seed)
    c = 50 * np.exp(np.cumsum(rng.normal(.004, .015, (n, k)), axis=0))
    o = c * (1 + rng.normal(0, .003, (n, k)))
    h, l = np.fmax(o, c) * 1.01, np.fmin(o, c) * .99
    days = np.array([str(np.datetime64('2024-01-02') + i) for i in range(n)])
    return dict(days=days, codes=np.array([f'US.T{j}' for j in range(k)]), market='us', open=o, high=h, low=l,
                close=c)


class Toy(S.Study):
    """Buys T0 on day 5 and T1 on the last day; trims at 1R, no trail."""
    name = 'Toy'

    def __init__(self, P):
        self.P = P

    def arrays(self, market, upto=None, mode=None):
        return dict(self.P)

    def build(self, A, cfg, trace=None):
        c, l = A['close'], A['low']
        n = len(c)
        entries = [[] for _ in range(n)]
        entries[5].append((0.0, 0, 1, float(c[5, 0]), float(c[5, 0] * .95), 'ep'))
        entries[n - 1].append((0.0, 1, 1, float(c[n - 1, 1]), float(l[n - 1, 1] * .99), 'pb'))
        entries[n - 1].append((1.0, 2, 1, float(c[n - 1, 2]), float(l[n - 1, 2] * .99), 'pb'))
        rules = Y.Rules(trail='', trims=(1,), trim_frac=.25, max_new_long=1)
        return entries, rules, np.zeros(c.shape, bool), np.ones(c.shape, bool)


def system(P, freeze):
    st = Toy(P)
    return SimpleNamespace(id='toy', study=st, config={}, name='Toy', version='V1', status='research', label='V1',
                           freeze=freeze, strategy={})


class RunnerTests(unittest.TestCase):
    def test_buys_wanted_and_holdings(self):
        P = panel()
        r = RN.run(system(P, P['days'][-1]), 'us')
        self.assertEqual([b['code'] for b in r['buys']], ['US.T1'])                  # one new long a day
        self.assertEqual([w['code'] for w in r['wanted']], ['US.T2'])
        held = {h['code']: h for h in r['holdings']}
        self.assertIn('US.T1', held)
        self.assertAlmostEqual(r['account']['exposure'], sum(h['weight'] for h in r['holdings']))

    def test_reported_stop_is_where_the_engine_exits_next(self):
        P = panel()
        r = RN.run(system(P, P['days'][-1]), 'us')
        h = next(x for x in r['holdings'] if x['code'] == 'US.T1')
        Q = {k: (np.vstack([v, v[-1:]]) if isinstance(v, np.ndarray) and v.ndim == 2 else v) for k, v in P.items()}
        Q['days'] = np.append(P['days'], str(np.datetime64(P['days'][-1]) + 1))
        j = 1
        Q['open'][-1, j] = h['stop'] * 1.02                       # opens above the stop, trades through it
        Q['low'][-1, j] = h['stop'] * .97
        Q['high'][-1, j] = h['stop'] * 1.03
        Q['close'][-1, j] = h['stop'] * .98
        Q2 = dict(Q)
        st = Toy(Q2)
        entries, rules, _, pool = Toy(P).build(P, {})
        entries = entries + [[]]
        _, _, tr = Y.simulate(st.px(Q2), {}, rules, entries, Q['days'][0], Q['days'][-1], audit=True)
        t = next(x for x in tr if x['code'] == 'US.T1')
        self.assertEqual(t['why'], 'stop')
        self.assertAlmostEqual(t['executions'][-1]['price'], h['stop'])

    def test_forward_starts_after_the_freeze(self):
        P = panel()
        r = RN.run(system(P, P['days'][-11]), 'us')
        self.assertEqual(r['forward']['days'], 10)
        r = RN.run(system(P, P['days'][-1]), 'us')
        self.assertEqual(r['forward']['days'], 0)

    def test_years_until_ignores_days_after_the_freeze(self):
        days = np.array(['2024-12-30', '2024-12-31', '2025-01-02', '2025-01-03'])
        curve = np.array([1.0, 1.1, 1.21, 2.0])
        self.assertEqual(RN.years_until(curve, days, '2025-01-02'), {'2024': 1.1 - 1, '2025': 1.21 / 1.1 - 1})


if __name__ == '__main__':
    unittest.main()
