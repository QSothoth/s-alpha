"""I3 intraday confidence (confidence.py, intraday_i3.py): trading time with the lunch break, the bar known at each
cut, nothing after t or of today's close entering the features and the scenario rows, the volume and probability
models, the thresholds, the candidate features, and (with the local HK data) the scenario rerun equal to a whole
rebuild."""
import unittest
from pathlib import Path

import numpy as np

from studies.trader_screens import confidence as CF, intraday_i3 as I3

ROOT = Path(__file__).resolve().parents[3]


class TimeTests(unittest.TestCase):
    def test_trading_time_skips_lunch(self):
        self.assertEqual(CF.total('us'), 390)
        self.assertEqual(CF.total('hk'), 330)
        self.assertEqual(CF.total('cn'), 240)
        self.assertEqual(CF.elapsed('hk', '12:30'), 150)              # in the lunch break: the morning only
        self.assertEqual(CF.elapsed('hk', '13:30'), 180)
        self.assertEqual(CF.elapsed('cn', '13:30'), 150)
        self.assertAlmostEqual(CF.tau('us', '15:50'), 380 / 390)
        self.assertEqual(CF.back30('hk', '13:30'), '12:00')
        self.assertEqual(CF.back30('cn', '13:30'), '11:30')
        self.assertEqual(CF.back30('us', '15:50'), '15:20')
        self.assertIsNone(CF.back30('us', '10:00'))
        self.assertEqual(CF.clock('hk', 150), '12:00')
        for m in ('us', 'hk', 'cn'):                                    # every cut, and its 30 minutes back, gathered
            self.assertTrue(set(CF.CUTS[m]) <= set(I3.agg_cuts(m)))
            self.assertIn(CF.MAIN[m], CF.CUTS[m])


def bars(day='2026-10-19', code='US.A'):
    out = []
    for i, hh in enumerate(['09:35', '10:00', '10:05', '12:00', '15:50', '15:55', '16:00']):
        out.append((code, day, hh, 10 + i, 11 + i, 9 + i, 10.5 + i, 100.0 * (i + 1), 1000.0 * (i + 1)))
    return out


class SessionTests(unittest.TestCase):
    def test_parts_hold_only_bars_ended_by_the_cut(self):
        cuts = ('10:00', '12:00', '15:50')
        (code, day, parts, full), = list(I3._sessions(iter(bars()), 'us', cuts))
        np.testing.assert_allclose(parts[0], (10, 12, 9, 11.5, 300, 3000))     # 09:35 and 10:00
        np.testing.assert_allclose(parts[1], (10, 14, 9, 13.5, 1000, 10000))
        np.testing.assert_allclose(full, (10, 17, 9, 16.5, 2800, 28000))
        later = [r if r[2] <= '15:50' else r[:3] + (1, 99, .1, 50, 1e9, 1e9) for r in bars()]
        (_, _, p2, f2), = list(I3._sessions(iter(later), 'us', cuts))
        np.testing.assert_array_equal(p2, parts)                               # bars after a cut cannot reach it
        self.assertFalse(np.allclose(f2, full))

    def test_incomplete_sessions_dropped(self):
        b = bars()
        self.assertEqual(list(I3._sessions(iter(b[1:]), 'us', ('12:00',)))[0][0], 'US.A')    # first bar 10:00
        self.assertEqual(list(I3._sessions(iter(b[:-1]), 'us', ('12:00',))), [])   # no closing bar
        late = [r[:2] + ('10:05',) + r[3:] for r in b[:1]] + b[2:]
        self.assertEqual(len(list(I3._sessions(iter(late), 'us', ('12:00',)))), 0)


def panel(n=40, k=3, seed=1):
    r = np.random.default_rng(seed)
    close = 10 * np.exp(np.cumsum(r.normal(0, .02, (n, k)), 0))
    P = dict(days=np.array([f'2026-01-{i + 1:02d}' if i < 31 else f'2026-02-{i - 30:02d}' for i in range(n)]),
             codes=np.array(['US.A', 'US.B', 'US.C'][:k]), open=close * .99, high=close * 1.02, low=close * .97,
             close=close, volume=r.uniform(1e5, 2e5, (n, k)), turnover=close * 1.5e5, raw_close=close.copy())
    return {kk: (v.astype(np.float32) if isinstance(v, np.ndarray) and v.dtype.kind == 'f' else v)
            for kk, v in P.items()}


def sessions(P, d, cuts, scale_after=None):
    """S of one day: every code's minute session (parts per cut); scale_after: bars after that cut changed."""
    n = len(P['codes'])
    parts = np.zeros((n, len(cuts), 6), np.float32)
    full = np.zeros((n, 6), np.float32)
    for j in range(n):
        o = float(P['open'][d, j])
        for i, c in enumerate(cuts):
            f = (i + 1) / len(cuts)
            parts[j, i] = (o, o * 1.01, o * .99, o * (1 + .001 * i), 1e5 * f, 1e6 * f)
        full[j] = parts[j, -1]
        if scale_after is not None:
            for i, c in enumerate(cuts):
                if c > scale_after:
                    parts[j, i, 1:] *= 3
            full[j, 1:] *= 3
    return dict(j=np.arange(n, dtype=np.int32), d=np.full(n, d, np.int32), recent=np.ones(n, bool), parts=parts,
                full=full, conv=np.full((n, 2), np.nan), cuts=np.array(cuts))


class NoFutureTests(unittest.TestCase):
    """What a provisional run at t sees must not move when the bars after t or today's closing bar move."""

    def state_at(self, P, S, cut):
        st = I3.states(P, I3.rolling(P), S, np.arange(len(S['j'])), 'us')
        n = CF.CUTS['us'].index(cut)
        keys = ('op', 'prev', 'fac', 'adv', 'to20', 'adr')
        return {k: st[k] for k in keys} | {f'cut_{k}': v for k, v in st[n].items()}

    def test_states_use_bars_up_to_t_and_days_before(self):
        P = panel()
        d = 35
        cuts = I3.agg_cuts('us')
        base = self.state_at(P, sessions(P, d, cuts), '11:00')
        later = self.state_at(P, sessions(P, d, cuts, scale_after='11:00'), '11:00')
        Q = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in P.items()}
        for k in ('high', 'low', 'close', 'volume', 'turnover', 'raw_close'):   # today's true bar (not the open)
            Q[k][d] *= 1.7
        Q['close'][d + 1:] *= 5                                                    # and every later day
        moved = self.state_at(Q, sessions(Q, d, cuts), '11:00')
        for got in (later, moved):
            for k, v in base.items():
                np.testing.assert_allclose(got[k], v, err_msg=k)

    def test_scenario_rows_ignore_todays_true_bar(self):
        P = panel()
        d = 35
        prov = dict(j=[0, 2], high=[11, 12], low=[9, 10], close=[10, 11], volume=[1e5, 2e5], turnover=[1e6, 2e6],
                    adr=[.04, .06], k=[1, 1])
        yq = np.array([[.2, .5, .9], [.1, .3, .6]])
        a = CF.scenario_rows(P, d, prov, yq, .5)
        Q = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in P.items()}
        for k in ('high', 'low', 'close', 'volume', 'turnover', 'raw_close'):
            Q[k][d] *= 1.7
        b = CF.scenario_rows(Q, d, prov, yq, .5)
        for name in a:
            for k in a[name]:
                np.testing.assert_allclose(a[name][k][[0, 2]], b[name][k][[0, 2]], err_msg=f'{name} {k}')
        self.assertEqual(a['V0']['volume'][0], 1e5)                              # V0: volume so far
        self.assertAlmostEqual(a['M']['volume'][0], 1e5 * np.exp(.5))
        self.assertAlmostEqual(a['VH']['volume'][2], 2e5 * np.exp(.6))
        u = .04 * np.sqrt(.5)
        s = CF.side_hash('US.A')
        self.assertAlmostEqual(a['A']['close'][0], 10 * (1 + CF.STEP * u * s), places=5)
        self.assertAlmostEqual(a['B']['close'][0], 10 * (1 - CF.STEP * u * s), places=5)
        self.assertGreaterEqual(a['A']['high'][0], a['A']['close'][0])
        np.testing.assert_allclose(a['M']['close'][1], P['close'][d, 1])          # names without a bar unchanged

    def test_volume_features_are_a_function_of_t_inputs(self):
        x = CF.vol_features(.5, .4, np.array([4e5, 1e5]), np.array([1e5, 1e4]), np.array([10., 20]),
                            np.array([9., 20]), np.array([1e6, 1e6]), np.array([1e7, 4e7]), np.array([.04, .02]),
                            np.array([11., 21]), np.array([9., 19]), np.array([10.5, 19.5]))
        self.assertAlmostEqual(x[0, 0], np.log(4e5 / 4e5))
        self.assertAlmostEqual(x[1, 1], 0.0)
        self.assertAlmostEqual(x[0, 2], -x[1, 2])                                 # liquidity relative to the median
        self.assertAlmostEqual(x[0, 7], np.log(5e5 / 8e5))


class ModelTests(unittest.TestCase):
    def test_volume_models_quantiles_and_round_trip(self):
        r = np.random.default_rng(0)
        n = 6000
        X = r.normal(0, 1, (n, len(CF.VFEAT)))
        X[:, 1] = np.abs(X[:, 1]) * .03
        t = r.choice([.2, .5, .8], n)
        z = -.5 * X[:, 0] * np.sqrt(1 - t) + r.normal(0, .3, n)
        for kind in ('VG', 'VQ'):
            m = CF.VolumeModel(kind).fit(X, t, z, t)
            q = m.predict(X, t)
            self.assertTrue(np.all(np.diff(q, axis=1) >= 0))
            cover = np.mean((z >= q[:, 0]) & (z <= q[:, 2]))
            self.assertGreater(cover, .7, kind)
            self.assertLess(cover, .9, kind)
            m2 = CF.VolumeModel.from_json(CF.VolumeModel(kind).to_json() if False else m.to_json())
            np.testing.assert_allclose(m2.predict(X[:50], .35), m.predict(X[:50], .35))
        g = CF.VolumeModel('VG').fit(X, t, z, t)
        mid = g.predict(X[:5], .35)                      # between the .2 and .5 grids: the linear blend
        np.testing.assert_allclose(mid, np.sort(.5 * g.predict(X[:5], .2) + .5 * g.predict(X[:5], .5), axis=1))

    def test_probability_models_thresholds_round_trip(self):
        r = np.random.default_rng(1)
        n = 3000
        X = np.zeros((n, len(CF.PFEAT)))
        X[:, 0] = r.integers(0, 2, n)
        X[:, 5] = X[:, 0] + r.integers(0, 5, n)
        X[:, 6] = r.uniform(0, 1, n)
        X[:, 7] = X[:, 6] * X[:, 0]
        X[:, 9] = 1
        y = r.uniform(0, 1, n) < .1 + .7 * X[:, 0] * X[:, 6]
        for kind in ('PL', 'PG'):
            m = CF.ProbModel(kind).fit(X, y)
            p = m.predict(X)
            self.assertGreater(p[(X[:, 0] == 1) & (X[:, 6] > .9)].mean(), p[X[:, 0] == 0].mean() + .4)
            np.testing.assert_allclose(CF.ProbModel.from_json(m.to_json()).predict(X[:20]), p[:20])
        hi, lo = CF.thresholds(np.array([.9, .85, .6, .55, .3, .1]), np.array([1, 1, 1, 0, 1, 0]),
                               np.ones(6, bool))
        self.assertEqual(hi, .15)                        # the smallest grid value with 4 of 5 right
        self.assertLessEqual(lo, hi)
        hi, lo = CF.thresholds(np.array([.9, .85, .6, .55, .3, .1]), np.array([1, 1, 0, 0, 1, 0]),
                               np.ones(6, bool))
        self.assertEqual(hi, .65)
        self.assertEqual(lo, .3)                         # .3 keeps every true one in order + watch


class CandidateTests(unittest.TestCase):
    def test_up_down_follow_the_name_and_favour_the_side(self):
        up_code = next(c for c in ('US.A', 'US.B', 'US.C', 'US.D') if CF.side_hash(c) > 0)
        dec = lambda buys=(), sells=(): {'x': dict(sig=[], buys=list(buys), sells=list(sells))}
        buy = [up_code, 1, False, 10.0, 9.0, 'ep']
        sell = [up_code, 1, 9.5, '收盘跌破跟踪线']
        by = dict(M=dec(), A=dec([buy], [sell]), B=dec(), VL=dec(), VH=dec([buy]))
        rows = {r['key'][0]: r for r in CF.candidates(by, .5)}
        self.assertEqual(rows['buy']['bits'], dict(M=False, up=True, dn=False, VL=False, VH=True))
        self.assertEqual(rows['buy']['cls'], 'ep')
        self.assertEqual(rows['sell']['cls'], 'close')
        X = CF.pfeatures([rows['buy'], rows['sell']])
        f = {k: i for i, k in enumerate(CF.PFEAT)}
        self.assertEqual((X[0, f['fav']], X[0, f['unfav']]), (1, 0))            # a long buy wants the price up
        self.assertEqual((X[1, f['fav']], X[1, f['unfav']]), (0, 1))            # a long's exit wants it down
        self.assertIn('再涨', CF.distance(rows['buy'], .04))
        self.assertIn('q90', CF.distance(rows['buy'], .04))


class LiveTests(unittest.TestCase):
    def test_daily_inputs_equal_the_research_rolling(self):
        P = panel()
        R = I3.rolling(P)
        j = np.arange(3)
        for d in (25, 39):
            got = CF.daily_inputs(P, d, j)
            for k in ('adv', 'to20', 'adr'):
                np.testing.assert_allclose(got[k], R[k][d, j], rtol=1e-6, err_msg=k)

    def model(self):
        r = np.random.default_rng(0)
        X = r.normal(0, 1, (2000, len(CF.VFEAT)))
        t = r.choice([CF.tau('us', c) for c in CF.CUTS['us']], 2000)
        vm = CF.VolumeModel('VG').fit(X, t, r.normal(0, .3, 2000), t)
        F = np.zeros((400, len(CF.PFEAT)))
        F[:, 0] = np.arange(400) % 2
        F[:, 5] = F[:, 0]
        pm = CF.ProbModel('PG').fit(F, F[:, 0] == 1)
        fm = {'us': {c: CF.tau('us', c) for c in CF.CUTS['us']}}
        return vm, pm, fm, dict(p_hi=.8, p_lo=.3), dict(integrate=True)

    def test_columns_from_the_scenarios(self):
        from unittest import mock
        P = panel()
        P['volume'][-1] = 5e4                              # today's volume so far
        seen = {}

        def fake(p, d, rows, market, systems=None):
            seen['rows'] = rows
            buy = ['US.A', 1, False, float(p['close'][d, 0]), 9.0, 'brk']
            sell = ['US.B', 1, 9.0, '收盘跌破跟踪线']
            return {n: {'x': dict(sig=[], buys=[buy] if n != 'VL' else [], sells=[sell] if n == 'VH' else [])}
                    for n in rows}
        with mock.patch.object(CF, 'decide_many', fake):
            c = CF.live(P, 'us', '11:00', self.model())
            self.assertIn('skipped', CF.live(P, 'us', '09:50', self.model()))
        self.assertEqual(sorted(seen['rows']), sorted(CF.SCEN))
        rows = {x['code']: x for x in c['rows']}
        self.assertEqual(rows['US.A']['column'], 'order')        # in M: the PG cell of in-M rows, p ~ 1
        self.assertIsNone(rows['US.B']['column'])                 # only at q90 volume: p ~ 0
        self.assertIn('q10', rows['US.A']['distance'])            # gone at q10 volume
        self.assertAlmostEqual(c['t'], CF.tau('us', '11:00'))

    def test_early_board_keeps_only_orders_standing_in_every_scenario(self):
        from unittest import mock
        P = panel()
        P['volume'][-1] = 5e4
        seen = {}

        def board(market, mode, days, only, panel=None):
            seen['close'] = float(panel['close'][-1, 0])
            buy = lambda c: dict(code=c, side=1, setup='brk', price=10.0, stop=9.0, weight=.1)
            return dict(market=market, last_day=str(panel['days'][-1]), traders=[dict(
                id='x', name='X', buys=[buy('US.A'), buy('US.B')], sells=[dict(code='US.C', side=1, why='跌破止损')])])

        def fake(p, d, rows, market, systems=None):
            seen['rows'] = sorted(rows)
            out = {}
            for n in rows:
                buys = [['US.A', 1, False, 10.0, 9.0, 'brk']] + ([['US.B', 1, False, 10.0, 9.0, 'brk']] if n == 'M' else [])
                out[n] = {'x': dict(sig=[], buys=buys, sells=[['US.C', 1, 9.0, '跌破止损']])}
            return out
        with mock.patch.object(CF, 'decide_many', fake):
            r = CF.robust_board(P, 'us', '10:30', board, model=LiveTests.model(self))
            with self.assertRaises(ValueError):
                CF.robust_board(P, 'us', '09:50', board, model=LiveTests.model(self))
        self.assertEqual(seen['rows'], sorted(CF.SCEN))
        self.assertAlmostEqual(seen['close'], float(P['close'][-1, 0]), places=4)    # scenario M: today's price
        t = r['traders'][0]
        self.assertEqual([b['code'] for b in t['buys']], ['US.A'])                     # B only in M: not listed
        self.assertEqual([s['code'] for s in t['sells']], ['US.C'])
        self.assertEqual([(x['code'], x['kind']) for x in r['early']['dropped']], [('US.B', 'buy')])
        self.assertEqual(r['early']['kept'], 2)

    def test_board_shows_both_columns(self):
        from studies.trader_screens import board
        rows = [dict(trader='x', kind='buy', code='US.A', name='A', side=1, add=False, setup='ep', price=10.0, p=.91,
                     column='order', distance='跌 1.0% 会失效', direct=True),
                dict(trader='x', kind='sell', code='US.B', name='B', side=1, add=False, setup='收盘跌破跟踪线',
                     price=9.0, p=.4, column='watch', distance='再跌 1.0% 内可触发')]
        r = dict(traders=[dict(id='x', name='X')],
                 confidence=dict(hhmm='11:00', t=.23, thresholds=dict(p_hi=.8, p_lo=.3), rows=rows))
        text = '\n'.join(board.confidence(r))
        self.assertIn('下单（1）', text)
        self.assertIn('观察（1）', text)
        self.assertIn('0.91', text)
        self.assertIn('破跟踪线', text)


@unittest.skipUnless((ROOT / 'data' / 'trader-screens' / 'k5').exists(), 'needs the local HK data')
class FastRerunTests(unittest.TestCase):
    def test_scenario_rerun_equals_a_whole_rebuild(self):
        from studies.trader_screens import intraday_study as IS, minute as MN
        try:
            P = IS.panel('hk')
            path = MN.latest('hk')
        except (SystemExit, Exception) as e:              # no live HK data here
            self.skipTest(str(e))
        d = len(P['days']) - 2
        day = str(P['days'][d])
        b = {c: s['parts'] for (c, _), s in MN.aggregate(MN.stream(path, {day}), ('11:00',)).items()
             if MN.complete(s, 'hk')}
        if not b:
            self.skipTest('no minute bars of that day')
        row, _ = IS.provisional_row(P, d, b, '11:00')
        true = {k: P[k][d].astype(float).copy() for k in ('open', 'high', 'low', 'close', 'volume', 'turnover')}
        got = CF.decide_many(P, d, {'true': true, 'prov': row}, 'hk')
        ref = IS.decide(IS.cut_at(P, d, row), 'hk', day)
        for sid, r in ref.items():
            g = got['prov'][sid]
            key = lambda xs: sorted(str([x if not isinstance(x, float) else round(x, 6) for x in z]) for z in xs)
            self.assertEqual(key([z[:5] for z in g['buys']]), key(r['buys']), sid)
            self.assertEqual(key(g['sells']), key(r['sells']), sid)
            self.assertEqual(key(g['sig']), key(r['sig']), sid)


if __name__ == '__main__':
    unittest.main()
