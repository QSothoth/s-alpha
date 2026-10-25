"""Regression tests for the fixes of the 2026-10-25 strategy review (studies/trader_screens/reports/
STRATEGY_REVIEW_20261025_CN.md): the review's fixtures, now asserting the corrected behaviour."""
import unittest
from dataclasses import replace
from types import SimpleNamespace

import numpy as np

from studies.trader_replication import runner, shorts as SH, system as Y, systems
from studies.trader_replication.tests.test_shorts import arrays
from studies.trader_replication.tests.test_system import NOCOST, one, px


def two(later_close):
    return dict(open=np.array([[100., 10.], [100., 10.]]), high=np.array([[101., 10.5], [200., 10.5]]),
                low=np.array([[90., 9.5], [90., 9.5]]), close=np.array([[100., 10.], [later_close, 10.]]),
                dates=np.array(['2025-01-02', '2025-01-03']), codes=np.array(['US.A', 'US.B']))


def open_short(p, sc=None):
    a = dict(p, days=p['dates'], adr=np.full((2, 2), 20.), to20=np.full((2, 2), 1e8))
    armed = np.array([[False, False], [False, True]])
    return SH.short_entries(a, {'ptop': dict(armed=armed, at_open=True)}, sc or {'stop_w': .1})


class FillTime(unittest.TestCase):
    """R01: a short sold at the open (a declared intraday kind) is sized and admitted on the account as of the open."""

    def test_open_short_size_does_not_read_the_later_close(self):
        sizes = []
        for later in (100., 200.):
            p = two(later)
            e = open_short(p)
            e[0].append((0., 0, 1, 100., 50., 'long'))
            r = Y.Rules(risk=.1, max_position=2., max_gross=5., trail='', trims=(), intraday_kinds=('s_ptop',),
                        **NOCOST)
            _, _, tr = Y.simulate(p, {}, r, e, p['dates'][0], p['dates'][-1], audit=True)
            sizes.append(next(t for t in tr if t['side'] < 0)['executions'][0]['shares'])
        self.assertAlmostEqual(*sizes)

    def test_slot_freed_at_the_close_is_not_used_at_the_open(self):
        p = two(100.)
        e = open_short(p)
        e[0].append((0., 0, 1, 100., 50., 'long'))
        r = Y.Rules(max_open=1, max_days=1, trail='', trims=(), intraday_kinds=('s_ptop',), **NOCOST)
        _, _, tr = Y.simulate(p, {}, r, e, p['dates'][0], p['dates'][-1], audit=True)
        self.assertEqual([t['side'] for t in tr], [1])          # the long's time exit at the close comes too late

    def test_fill_off_the_close_counts_as_intraday_without_declaration(self):
        p = two(100.)
        e = [[(0., 0, 1, 100., 50., 'long')], [(0., 1, -1, 10.2, 11., 's_lim')]]   # 10.2 is not the 10.0 close
        r = Y.Rules(max_open=1, max_days=1, trail='', trims=(), **NOCOST)
        _, _, tr = Y.simulate(p, {}, r, e, p['dates'][0], p['dates'][-1], audit=True)
        self.assertEqual([t['side'] for t in tr], [1])

    def test_close_entries_still_use_the_slot_freed_that_close(self):
        p = two(100.)
        e = [[(0., 0, 1, 100., 50., 'long')], [(0., 1, 1, 10., 9., 'long')]]
        r = Y.Rules(max_open=1, max_days=1, trail='', trims=(), **NOCOST)
        _, _, tr = Y.simulate(p, {}, r, e, p['dates'][0], p['dates'][-1], audit=True)
        self.assertEqual(len(tr), 2)

    def test_wrapper_declares_level_shorts_intraday(self):
        st = SimpleNamespace(build=lambda A, cfg, trace=None: ([[] for _ in A['days']], Y.Rules(), np.zeros((2, 1), bool),
                                                               np.ones((2, 1), bool)),
                             short_setups=lambda A, sc: ({'lim': dict(armed=np.ones((2, 1), bool),
                                                                      level=np.full((2, 1), 10.)),
                                                          'cl': np.ones((2, 1), bool)}, np.ones((2, 1), bool)))
        A = arrays([(10, 10.2, 9.8, 10), (9.9, 10.4, 9.7, 10.1)])
        _, rules, _, _ = SH.LongShort(st).build(A, {'short': {'gate': ''}})
        self.assertEqual(rules.intraday_kinds, ('s_lim',))
        self.assertEqual(set(A['kind_pools']), {'s_lim', 's_cl'})


class Placebo(unittest.TestCase):
    def test_same_name_placebo_keeps_the_open_fill_and_day0_stop(self):
        """R02: one name in the pool: the placebo is the real trade."""
        a = arrays([(10, 10.1, 9.9, 10), (10, 10.1, 8, 8)])
        p = {k: a[k] for k in ('open', 'high', 'low', 'close', 'codes')}
        p['dates'] = a['days']
        e = SH.short_entries(a, {'ptop': dict(armed=np.array([[False], [True]]), at_open=True)}, {'stop_w': .1})
        r = Y.Rules(trail='', trims=(), intraday_kinds=('s_ptop',), **NOCOST)
        real = Y.simulate(p, {}, r, e, a['days'][0], a['days'][-1])[0][-1]
        control = Y.simulate(p, {}, r, e, a['days'][0], a['days'][-1], placebo=np.random.default_rng(1),
                             pool=np.ones((2, 1), bool))[0][-1]
        self.assertAlmostEqual(real, control)
        self.assertAlmostEqual(real, 1.01)

    def test_placebo_open_entry_stopped_that_day(self):
        a = arrays([(10, 10.1, 9.9, 10), (10, 12, 9, 9.5)])
        p = {k: a[k] for k in ('open', 'high', 'low', 'close', 'codes')}
        p['dates'] = a['days']
        e = [[], [(0., 0, -1, 10., 11., 's_x', 11.)]]
        r = Y.Rules(trail='', trims=(), intraday_kinds=('s_x',), **NOCOST)
        _, _, tr = Y.simulate(p, {}, r, e, a['days'][0], a['days'][-1], placebo=np.random.default_rng(1),
                              pool=np.ones((2, 1), bool), audit=True)
        self.assertEqual(tr[0]['why'], 'stop_day0')

    def test_placebo_draws_from_the_kinds_pool(self):
        """R03: an entry's random name comes from its own kind's pool when px carries one."""
        a = arrays([(10, 10.1, 9.9, 10), (10, 10.1, 9.9, 10)], n=3)
        p = {k: a[k] for k in ('open', 'high', 'low', 'close', 'codes')}
        p['dates'] = a['days']
        only2 = np.zeros((2, 3), bool)
        only2[:, 2] = True
        p['kind_pools'] = {'k': only2}
        e = [[], [(0., 0, 1, 10., 9., 'k')]]
        r = Y.Rules(trail='', trims=(), **NOCOST)
        for seed in range(5):
            _, _, tr = Y.simulate(p, {}, r, e, a['days'][0], a['days'][-1], placebo=np.random.default_rng(seed),
                                  pool=np.ones((2, 3), bool), audit=True)
            self.assertEqual(tr[0]['code'], 'US.S2')


class Management(unittest.TestCase):
    def test_signal_trim_once_keeps_the_trailing_rest(self):
        """R04: trim_signal_max=1 (Clement / Kell RV1): one third off, the rest trails."""
        p = px([(100, 101, 99, 100), (140, 141, 139, 140), (141, 142, 140, 141),
                (142, 143, 141, 142), (143, 144, 142, 143)])
        for sid in ('clement_ang', 'oliver_kell'):
            opts = {k: tuple(v) if isinstance(v, list) else v for k, v in systems.get(sid).config['rule_opts'].items()}
            self.assertEqual(opts['trim_signal_max'], 1)
            r = replace(Y.Rules(), **opts, **NOCOST)
            ema = {r.trail: np.full((5, 1), 90.), r.trim_signal: np.array([[False], [True], [True], [True], [True]])}
            _, _, tr = Y.simulate(p, ema, r, one(5, 0, 1, 100., 99.), p['dates'][0], p['dates'][-1], audit=True)
            actions = [x['action'] for x in tr[0]['executions']]
            self.assertEqual(actions.count('signal_trim'), 1, sid)
            self.assertEqual(tr[0]['why'], 'end', sid)

    def test_breakeven_reached_at_the_open_applies_that_day(self):
        """R05: open 13 is beyond the 2R trigger 12; the later low 9.5 passes the moved stop 10."""
        p = px([(10, 10, 10, 10), (13, 13, 9.5, 9.8)])
        _, _, tr = Y.simulate(p, {}, Y.Rules(trail='', trims=(), breakeven_r=2, **NOCOST),
                              [[(0, 0, 1, 10, 9, 'x')], []], p['dates'][0], p['dates'][-1], audit=True)
        self.assertEqual(tr[0]['why'], 'stop')
        self.assertEqual(tr[0]['executions'][-1]['price'], 10)

    def test_breakeven_reached_only_intraday_still_waits(self):
        p = px([(10, 10, 10, 10), (11, 13, 9.5, 9.8)])
        _, _, tr = Y.simulate(p, {}, Y.Rules(trail='', trims=(), breakeven_r=2, **NOCOST),
                              [[(0, 0, 1, 10, 9, 'x')], []], p['dates'][0], p['dates'][-1], audit=True)
        self.assertEqual(tr[0]['why'], 'end')
        self.assertEqual(tr[0]['state']['stop'], 10)

    def test_trims_in_adr_units(self):
        """M02: unit_adr: the 2-unit partial sits 2 ADR (5% each) above the fill, not 2R (stop 1% away)."""
        p = px([(100, 100, 100, 100), (100, 100, 100, 100), (100, 103, 99.5, 102), (102, 111, 101, 110)])
        adr = np.full((4, 1), 5.0)                                    # the ADR as of the session before entry
        r = Y.Rules(trail='', trims=(2,), trim_frac=.5, **NOCOST)
        e = one(4, 1, 1, 100., 99.)
        _, _, tr = Y.simulate(p, {}, r, e, p['dates'][0], p['dates'][-1], audit=True)
        self.assertEqual(tr[0]['executions'][1]['price'], 102)        # 2R = 102, reached on day 1
        _, _, tr = Y.simulate(p, {'adr': adr}, replace(r, unit_adr='adr'), e, p['dates'][0], p['dates'][-1],
                              audit=True)
        self.assertEqual([x['time'] for x in tr[0]['executions'] if x['action'] == 'trim'], ['2025-01-04'])
        self.assertEqual(tr[0]['executions'][1]['price'], 110)        # 2 ADR = 110, reached on day 2


class LimitUp(unittest.TestCase):
    def test_a_share_limit_up_close_is_not_bought(self):
        """R06: the skipped buy never reaches the account; the trace keeps it."""
        a = arrays([(10, 10, 10, 10), (10.5, 11, 10.5, 11), (11, 11.5, 11, 11.2)])
        a.update(market='cn', codes=np.array(['SH.600000']))
        e = [[], [(0., 0, 1, 11., 10.5, 'brk')], [(0., 0, 1, 11.2, 11., 'brk')]]
        trace = {}
        out = SH.limit_up_skip(a, e, Y.Rules(), trace)
        self.assertEqual(out[1], [])
        self.assertEqual(len(trace['limit_up'][1]), 1)
        self.assertEqual(len(out[2]), 1)                              # +1.8%: bought

    def test_mask_matches_the_boards_rule(self):
        from studies.trader_screens.intraday import at_limit_up
        rng = np.random.default_rng(0)
        prev = np.round(rng.uniform(2, 60, 400), 2)
        codes = np.array(['SH.600000', 'SZ.300001', 'SH.688001', 'SZ.000001'] * 100)
        step = np.where(np.char.startswith(codes, 'SZ.300') | np.char.startswith(codes, 'SH.688'), .2, .1)
        raw = np.round(prev * (1 + step * rng.choice([1, .99, 1.01, .5], 400)), 2)
        A = dict(raw=np.vstack([prev, raw]), close=np.vstack([prev, raw]), codes=codes,
                 days=np.array(['2026-08-03', '2026-08-04']), market='cn')
        lu = SH.limit_up_closes(A)
        want = [at_limit_up(c, '', r, p, '2026-08-04') for c, r, p in zip(codes, raw, prev)]
        self.assertEqual(lu[1].tolist(), want)
        self.assertFalse(lu[0].any())


class Runner(unittest.TestCase):
    def test_missing_latest_price_values_at_the_last_close(self):
        """R08: a holding without today's bar is valued as the engine does, and says so."""
        p = dict(open=np.array([[10.], [np.nan]]), high=np.array([[10.], [np.nan]]), low=np.array([[10.], [np.nan]]),
                 close=np.array([[10.], [np.nan]]), dates=np.array(['2024-01-02', '2024-01-03']),
                 codes=np.array(['US.A']))
        A = dict(p, days=p['dates'])
        rules = Y.Rules(trail='', trims=(), **NOCOST)
        entry = [[(0, 0, 1, 10, 9, 'toy')], []]
        st = SimpleNamespace(build=lambda A, cfg, trace=None: (entry, rules, None, None),
                             ema_inputs=lambda A, pool, rules: {}, px=lambda A: p, market_gate=lambda A, cfg: None)
        sys_ = SimpleNamespace(study=st, config={}, id='toy', name='toy', version='toy', status='research',
                               label='toy', strategy={}, freeze='2024-01-02')
        r = runner.run(sys_, 'us', A=A)
        h = r['holdings'][0]
        self.assertEqual(h['close'], 10.)
        self.assertEqual(h['close_day'], '2024-01-02')
        self.assertFalse(h['tradable'])
        self.assertTrue(np.isfinite(r['account']['exposure']))
        self.assertEqual(r['check']['status'], 'missing')

    def test_his_entry_uses_the_stop_cap(self):
        """M01: the second layer's stop follows the same rule as the system's entries."""
        from studies.christian_flanders.replicate import Flanders
        c, l = np.array([[95.], [100.]]), np.array([[90.], [80.]])
        e = Flanders().his_entry({'close': c, 'low': l}, 1, 0, {'stop_min': .01, 'stop_cap': .06})
        self.assertAlmostEqual(e[4], 94.)


if __name__ == '__main__':
    unittest.main()
