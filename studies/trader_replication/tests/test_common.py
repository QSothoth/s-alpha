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


class FloorTests(unittest.TestCase):
    def feat(self):
        from studies.trader_screens import screens as S
        n = 25
        p = {k: np.ones((n, 2)) * 10 for k in ('open', 'high', 'low', 'close', 'volume')}
        p.update(turnover=np.tile([30e6, 3e6], (n, 1)), raw_close=np.tile([10.0, 2.0], (n, 1)),
                 days=np.arange(n), codes=np.array(['US.A', 'US.B']))
        return S.Feat(p, 'us')

    def test_feat_floor_lowers_the_board_floor_for_one_build_only(self):
        F = self.feat()
        self.assertEqual(F.liquid(20e6)[-1].tolist(), [True, False])
        A = dict(arrays(25, 2), F=F)

        class Board(Fake):
            def build(self, A, cfg, trace=None):
                self.seen = A['F'].liquid(20e6)[-1].tolist()
                return super().build(A, cfg, trace)
        b = Board()
        b.own_floor = lambda cfg, t, p: cfg
        C.build_long(b, A, {'common': {'floor': [2e6, 1.0]}})
        self.assertEqual(b.seen, [True, True])
        self.assertIsNone(F.floor)                                   # reset after the build
        self.assertEqual(F.liquid(20e6)[-1].tolist(), [True, False])

    def test_own_floor_lowers_only_higher_floors(self):
        cfg = ST.Study().own_floor({'pool': {'turnover': 50e6, 'adr': 3.0}, 'ep_pool': {'turnover': 1e6, 'price': 2.0}},
                                   2e6, 1.0)
        self.assertEqual(cfg['pool'], {'turnover': 2e6, 'price': 1.0, 'adr': 3.0})
        self.assertEqual(cfg['ep_pool'], {'turnover': 1e6, 'price': 1.0})

    def test_small_names_get_the_position_cap_from_the_prior_day_turnover(self):
        A = arrays()
        A['to20'][1] = [5e6, 50e6, 5e6]
        A['to20'][2] = [50e6, 5e6, 50e6]                  # the day's own average is not used
        e = C.build_long(Fake(), A, {'common': {'small': [20e6, .1]}})[0]
        self.assertEqual([x[8] if len(x) > 8 else None for x in sorted(e[2], key=lambda x: x[1])], [.1, None, .1])


class ExecTests(unittest.TestCase):
    """exec: a long confirmed at day 2's close (planned fill 10, stop 9.5) is bought on day 3 or not at all."""

    def run_(self, mode, o, h=10.5, l=9.6, A=None, cfg=None):
        A = A or arrays(5, 3)
        A['open'][3, 0], A['high'][3, 0], A['low'][3, 0] = o, h, l
        e = C.build_long(Fake(), A, dict(cfg or {}, common={'exec': {'mode': mode}}))[0]
        self.assertEqual(e[2], [])                                     # never on the confirming day
        x = [q for q in e[3] if q[1] == 0]
        return x[0] if x else None

    def fill(self, mode, o, h=10.5, l=9.6):
        x = self.run_(mode, o, h, l)
        return x and x[3]

    def test_open_modes_read_only_the_next_open(self):
        self.assertEqual(self.fill('open', 10.4), 10.4)
        self.assertEqual(self.fill('open_up', 10.4), 10.4)
        self.assertIsNone(self.fill('open_up', 10.0))
        self.assertEqual(self.fill('open_down', 10.0), 10.0)
        self.assertIsNone(self.fill('open_down', 10.4))

    def test_limit_and_stop_orders_at_the_planned_fill(self):
        self.assertEqual(self.fill('limit', 9.8), 9.8)                 # opens below: the open
        self.assertEqual(self.fill('limit', 10.4, l=9.9), 10.0)        # trades down to it
        self.assertIsNone(self.fill('limit', 10.4, l=10.1))
        self.assertEqual(self.fill('stop', 10.4), 10.4)                # opens above: the open
        self.assertEqual(self.fill('stop', 9.8, h=10.2), 10.0)         # trades up to it
        self.assertIsNone(self.fill('stop', 9.8, h=9.9))

    def test_stop_kept_no_fill_under_it_stopped_the_same_day(self):
        x = self.run_('open', 10.4)
        self.assertEqual((x[4], x[6]), (9.5, None))                    # the planned stop, not moved
        self.assertIsNone(self.fill('open', 9.4, l=9.3))               # opens under the stop
        x = self.run_('open', 10.4, l=9.4)
        self.assertEqual(x[6], 9.5)
        A = arrays(5, 3)
        A['open'][3, 0], A['low'][3, 0] = 10.4, 9.4
        e, rules, _, _ = C.build_long(Fake(), A, {'common': {'exec': {'mode': 'open'}}})
        rules = replace(rules, max_new_long=1, risk=.01, max_position=.2, max_gross=10.0)
        px = dict(open=A['open'], high=A['high'], low=A['low'], close=A['close'], dates=A['days'], codes=A['codes'])
        _, _, tr = Y.simulate(px, {}, rules, e, A['days'][0], A['days'][-1], audit=True)
        self.assertEqual((tr[0]['code'], tr[0]['entry'], tr[0]['exit'], tr[0]['fill']),
                         ('US.S0', A['days'][3], A['days'][3], 10.4))

    def test_open_pct_carries_the_planned_width(self):
        x = self.run_('open_pct', 10.4, l=9.9)
        self.assertAlmostEqual(x[4], 10.4 * .95)                       # 5% under the fill, like 9.5 under 10
        self.assertIsNone(x[6])                                        # low 9.9 > 9.88: not stopped that day
        x = self.run_('open_pct', 10.4, l=9.8)
        self.assertAlmostEqual(x[6], 10.4 * .95)

    def test_last_day_has_no_next_day(self):
        A = arrays(3, 3)
        e = C.build_long(Fake(), A, {'common': {'exec': {'mode': 'open'}}})[0]
        self.assertEqual(sum(map(len, e)), 0)

    def test_close_mode_is_unchanged_outside_a_shares(self):
        A = arrays(5, 3)
        self.assertEqual(C.build_long(Fake(), A, {'common': {'exec': {'mode': 'close'}}})[0], Fake().build(A, {})[0])

    def test_build_cap_counts_only_filled_entries(self):
        A = arrays(5, 3)
        A['open'][3] = [9.9, 10.2, 10.2]
        e = C.build_long(Fake('build'), A, {'max_new': 1, 'common': {'exec': {'mode': 'open_up'}}})[0]
        self.assertEqual([x[1] for x in e[3]], [1])                    # 0 did not fill; 1 takes the slot

    def cn(self, codes=('SZ.000001', 'SZ.300001', 'SH.600001')):
        A = arrays(5, 3)
        A.update(market='cn', codes=np.array(codes))
        return A

    def test_a_share_limit_up_close_or_open_is_not_bought(self):
        A = self.cn()
        A['close'][1] = 9.09                                           # day 2 closes at 10.00 = 9.09 x 1.1
        A['raw'][1] = 9.09
        e = C.build_long(Fake(), A, {'common': {'exec': {'mode': 'close'}}})[0]
        self.assertEqual(sorted(x[1] for x in e[2]), [1])              # ChiNext's 20% limit: only 1 still bought
        A = self.cn()
        A['open'][3] = 11.0                                            # 10.00 -> 11.00: limit open on the main board
        e = C.build_long(Fake(), A, {'common': {'exec': {'mode': 'open'}}})[0]
        self.assertEqual(sorted(x[1] for x in e[3]), [1])
        A = self.cn()
        A['open'][3] = 10.95                                           # under the limit: bought
        e = C.build_long(Fake(), A, {'common': {'exec': {'mode': 'open'}}})[0]
        self.assertEqual(sorted(x[1] for x in e[3]), [0, 1, 2])

    def test_limit_uses_the_unadjusted_cent(self):
        A = self.cn(('SZ.000001',) * 3)
        A['close'][1], A['close'][2] = 3.33, 3.66                      # 3.33 x 1.1 = 3.663 -> limit 3.66
        A['raw'][1], A['raw'][2] = 3.33, 3.66
        self.assertTrue(C.at_limit(A, A['close'], 2)[0])
        A['close'][2] = A['raw'][2] = 3.65
        self.assertFalse(C.at_limit(A, A['close'], 2)[0])
        A['raw'][1], A['raw'][2] = 6.66, 7.33                          # adjusted 2:1: 6.66 x 1.1 = 7.326 -> 7.33
        A['close'][2] = 3.665
        self.assertTrue(C.at_limit(A, A['close'], 2)[0])
        A['raw'][2], A['close'][2] = 7.32, 3.66                        # a cent under on the unadjusted scale
        self.assertFalse(C.at_limit(A, A['close'], 2)[0])


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
