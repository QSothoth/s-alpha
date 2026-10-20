"""Shared mechanisms (common.py): the day's reordering reads only what is known at the entry close, EPs go first
when asked, a study that caps inside its build is cut after the reordering, and a configuration without `common`
passes through the long-short wrapper untouched."""
import unittest
from dataclasses import replace

import numpy as np

from studies.trader_replication import common as C, shorts as SH, study as ST, system as Y


def arrays(n_days=4, n=3):
    days = np.array(['2025-01-%02d' % (i + 1) for i in range(n_days)])
    one = np.ones((n_days, n))
    return dict(open=10 * one, high=10.5 * one, low=9.5 * one, close=10 * one, raw=10 * one,
                to20=np.full((n_days, n), 10e6), turnover=np.full((n_days, n), 10e6), adr=5 * one,
                has=np.ones((n_days, n), bool), days=days, codes=np.array([f'US.S{j}' for j in range(n)]),
                market='us')


class Fake:
    """Three long entries on day 2 in his own order 0, 1, 2; name 2 is his EP."""
    daily_cap = 'engine'
    own_stop_off = ST.Study.own_stop_off

    def __init__(self, cap='engine'):
        self.daily_cap = cap

    def build(self, A, cfg, trace=None):
        e = [[] for _ in A['days']]
        for j, kind in ((0, 'brk'), (1, 'brk'), (2, 'ep')):
            e[2].append((float(j), j, 1, 10.0, 9.5, kind))
        if self.daily_cap == 'build' and cfg.get('max_new'):
            e = [sorted(lst, key=lambda x: x[0])[:cfg['max_new']] for lst in e]
        rules = Y.Rules(buy_cost=0, sell_cost=0, margin_rate=0, trail='', trims=())
        if trace is not None:
            trace['filtered'] = trace['capped'] = e
        return e, rules, np.zeros(A['close'].shape, bool), np.ones(A['close'].shape, bool)

    def ep_mask(self, A, cfg):
        return None


def order(entries, d=2):
    return [e[1] for e in sorted(entries[d], key=lambda e: e[0])]


class RankTests(unittest.TestCase):
    def test_rvol_uses_the_day_turnover_over_the_prior_average(self):
        A = arrays()
        A['turnover'][2] = [10e6, 30e6, 20e6]
        e = C.build_long(Fake(), A, {'common': {'rank': 'rvol'}})[0]
        self.assertEqual(order(e), [1, 2, 0])
        A['to20'][2] = [1e6, 100e6, 100e6]               # day 2's own 20-day average is not used for day 2
        A['turnover'][3] = [0, 0, 1e9]                   # nor the next day
        self.assertEqual(order(C.build_long(Fake(), A, {'common': {'rank': 'rvol'}})[0]), [1, 2, 0])
        A['to20'][1] = [1e6, 10e6, 10e6]                  # the day before's average is
        self.assertEqual(order(C.build_long(Fake(), A, {'common': {'rank': 'rvol'}})[0]), [0, 1, 2])

    def test_ep_first_then_own_order_or_rvol(self):
        A = arrays()
        A['turnover'][2] = [10e6, 30e6, 20e6]
        self.assertEqual(order(C.build_long(Fake(), A, {'common': {'rank': 'ep_own'}})[0]), [2, 0, 1])
        self.assertEqual(order(C.build_long(Fake(), A, {'common': {'rank': 'ep_rvol'}})[0]), [2, 0, 1])

    def test_build_capped_study_is_cut_after_the_reordering(self):
        A = arrays()
        A['turnover'][2] = [10e6, 30e6, 20e6]
        base = Fake('build')
        self.assertEqual(order(base.build(A, {'max_new': 2})[0]), [0, 1])
        e = C.build_long(base, A, {'max_new': 2, 'common': {'rank': 'rvol'}})[0]
        self.assertEqual(order(e), [1, 2])
        e = C.build_long(base, A, {'max_new': 2, 'common': {'other': 1}})[0]     # no rank: the same cut
        self.assertEqual(order(e), [0, 1])

    def test_shorts_are_left_alone(self):
        e = [[], [], [(5.0, 0, -1, 10.0, 10.5, 's_x'), (0.0, 1, 1, 10.0, 9.5, 'brk')]]
        A = arrays(3, 2)
        out = C.rerank(A, e, 'rvol', lambda d, x: False)
        self.assertEqual(out[2][0], e[2][0])
        self.assertEqual(out[2][1][1:], e[2][1][1:])


class StopWidthTests(unittest.TestCase):
    """Entries fill at 10 with the stop at 9.5 (5% wide); ADR 5% on every day unless changed."""

    def test_cap_moves_a_wide_stop_up_with_the_prior_day_adr(self):
        A = arrays()
        e = C.build_long(Fake(), A, {'common': {'stop': {'adr': .6}}})[0]       # 0.6 x 5% = 3%
        self.assertEqual([round(x[4], 6) for x in e[2]], [9.7, 9.7, 9.7])
        A['adr'][2] = 50.0                                # the day's own ADR is not used
        A['adr'][1] = 10.0                                # the day before's is: 6% > 5%, nothing moves
        e = C.build_long(Fake(), A, {'common': {'stop': {'adr': .6}}})[0]
        self.assertEqual([x[4] for x in e[2]], [9.5, 9.5, 9.5])

    def test_pct_and_ep_cap_and_skip(self):
        A = arrays()
        e = C.build_long(Fake(), A, {'common': {'stop': {'pct': .02}}})[0]
        self.assertEqual([round(x[4], 6) for x in e[2]], [9.8, 9.8, 9.8])
        e = C.build_long(Fake(), A, {'common': {'stop': {'adr': .6, 'adr_ep': 1.5}}})[0]
        self.assertEqual([round(x[4], 6) for x in e[2]], [9.7, 9.7, 9.5])        # name 2 is the EP: 7.5% cap
        e = C.build_long(Fake(), A, {'common': {'stop': {'adr': .6, 'adr_ep': 1.5, 'mode': 'skip'}}})[0]
        self.assertEqual([x[1] for x in e[2]], [2])

    def test_his_own_skip_is_replaced(self):
        seen = {}

        class Own(Fake):
            def build(self, A, cfg, trace=None):
                seen.update(cfg)
                return super().build(A, cfg, trace)
        C.build_long(Own(), arrays(), {'stop_adr': {'brk': 1.0}, 'common': {'stop': {'adr': 1.0}}})
        self.assertEqual(seen['stop_adr'], {})
        C.build_long(Own(), arrays(), {'stop_adr': {'brk': 1.0}, 'common': {'rank': 'rvol'}})
        self.assertEqual(seen['stop_adr'], {'brk': 1.0})

    def test_shorts_keep_their_stop(self):
        A = arrays(3, 2)
        e = [[], [], [(5.0, 0, -1, 10.0, 11.0, 's_x')]]
        self.assertEqual(C.stop_width(A, e, {'pct': .02}, lambda d, x: False), e)


class AddTests(unittest.TestCase):
    def test_add_switch_sets_the_engine_rule_on_his_signal_mask(self):
        A = arrays()
        e, rules, mask, pool = C.build_long(Fake(), A, {'common': {'add': {'frac': 1.0, 'max': 2, 'stop': 'keep'}}})
        self.assertEqual((rules.add_signal, rules.add_signal_frac, rules.add_signal_max, rules.add_signal_stop,
                          rules.add_signal_profit), ('common_sig', 1.0, 2, 'keep', True))
        self.assertIs(A['common_sig'], mask)
        rules = C.build_long(Fake(), arrays(), {'common': {'rank': 'rvol'}})[1]
        self.assertEqual(rules.add_signal, '')


class EpSlotTests(unittest.TestCase):
    def test_build_capped_study_keeps_its_cap_plus_the_ep_slots(self):
        A = arrays()
        e = C.build_long(Fake('build'), A, {'max_new': 1, 'common': {'ep_slots': 1}})[0]
        self.assertEqual(sorted(x[1] for x in e[2]), [0, 2])           # first non-EP + the EP
        self.assertEqual(order(Fake('build').build(A, {'max_new': 1})[0]), [0])

    def test_engine_counts_eps_on_their_own(self):
        A = arrays(5, 3)
        e, rules, _, _ = C.build_long(Fake(), A, {'common': {'ep_slots': 1}})
        rules = replace(rules, max_new_long=1, risk=.01, max_position=.2, max_gross=10.0)
        px = dict(open=A['open'], high=A['high'], low=A['low'], close=A['close'], dates=A['days'], codes=A['codes'])
        _, _, tr = Y.simulate(px, {}, rules, e, A['days'][0], A['days'][-1])
        self.assertEqual(sorted(t['code'] for t in tr), ['US.S0', 'US.S2'])
        _, _, tr = Y.simulate(px, {}, replace(rules, max_new_by_kind={}), e, A['days'][0], A['days'][-1])
        self.assertEqual([t['code'] for t in tr], ['US.S0'])               # without: the EP waits behind the cap


class PassThroughTests(unittest.TestCase):
    def test_without_common_the_wrapper_calls_the_study_build(self):
        A = arrays()
        base = Fake()
        a = SH.wrap(base).build(A, {'max_new': 2})
        b = base.build(A, {'max_new': 2})
        self.assertEqual(a[0], b[0])
        c = SH.wrap(base).build(A, {'max_new': 2, 'common': {}})          # an empty dict is off too
        self.assertEqual(c[0], b[0])


if __name__ == '__main__':
    unittest.main()
