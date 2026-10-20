"""Human-sized trading (human.py and the engine fields it uses): when each limit binds within a session, that sizing
tiers scale the risk and cap the name (adds too), that the placebo keeps the tier, and that a configuration without
`human` is untouched."""
import unittest
from dataclasses import replace

import numpy as np

from studies.trader_replication import human as H, shorts as SH, system as Y

DATES = np.array(['2024-12-30', '2024-12-31', '2025-01-02', '2025-01-03'])
RULES = dict(buy_cost=0, sell_cost=0, margin_rate=0, trail='', trims=(), risk=.01, max_position=10.0,
             max_gross=10.0)
N = 5


def px(close=None, low=None, high=None, open_=None):
    c = np.full((len(DATES), N), 10.0) if close is None else close
    return {'open': c.copy() if open_ is None else open_, 'high': c + .1 if high is None else high,
            'low': c - .1 if low is None else low, 'close': c, 'dates': DATES,
            'codes': np.array([f'US.S{j}' for j in range(N)])}


def run(entries, p=None, **kw):
    track = {}
    _, _, tr = Y.simulate(p or px(), {}, Y.Rules(**{**RULES, **kw}), entries, DATES[0], DATES[-1], audit=True,
                          track=track)
    return sorted((t['code'], t['entry'], t['side']) for t in tr), tr, track


def empty():
    return [[] for _ in DATES]


class DailyAndYearlyLimits(unittest.TestCase):
    def test_new_positions_a_session_count_both_sides_and_every_kind(self):
        e = empty()
        e[0] += [(0, 0, 1, 10.0, 9.5, 'brk'), (1, 1, 1, 10.0, 9.5, 'ep'), (2, 2, -1, 10.0, 10.5, 's_x'),
                 (3, 3, 1, 10.0, 9.5, 'brk')]
        got = run(e, max_new_all=2, max_new_by_kind={'ep': 1})[0]
        self.assertEqual(got, [('US.S0', '2024-12-30', 1), ('US.S1', '2024-12-30', 1)])
        got = run(e, max_new_all=3)[0]                        # the short is the day's third
        self.assertIn(('US.S2', '2024-12-30', -1), got)
        self.assertNotIn(('US.S3', '2024-12-30', 1), got)

    def test_a_failed_open_does_not_use_a_place(self):
        e = empty()
        e[0] += [(0, 0, 1, 10.0, 10.5, 'brk'), (1, 1, 1, 10.0, 9.5, 'brk')]   # the first has its stop above
        self.assertEqual(run(e, max_new_all=1)[0], [('US.S1', '2024-12-30', 1)])

    def test_the_limit_resets_each_session(self):
        e = empty()
        e[0] += [(0, 0, 1, 10.0, 9.5, 'brk'), (1, 1, 1, 10.0, 9.5, 'brk')]
        e[1] += [(0, 2, 1, 10.0, 9.5, 'brk')]
        self.assertEqual([x[0] for x in run(e, max_new_all=1)[0]], ['US.S0', 'US.S2'])

    def test_a_calendar_year_limit_resets_on_the_first_session_of_the_year(self):
        e = empty()
        e[0] += [(0, 0, 1, 10.0, 9.5, 'brk')]
        e[1] += [(0, 1, 1, 10.0, 9.5, 'brk')]                 # 2024's second: over the limit of 1
        e[2] += [(0, 2, 1, 10.0, 9.5, 'brk')]                 # 2025's first
        e[3] += [(0, 3, 1, 10.0, 9.5, 'brk')]
        self.assertEqual([x[0] for x in run(e, max_new_year=1)[0]], ['US.S0', 'US.S2'])

    def test_off_by_default(self):
        e = empty()
        e[0] += [(k, k, 1, 10.0, 9.5, 'brk') for k in range(4)]
        self.assertEqual(len(run(e)[0]), 4)


class NoRebuySameDay(unittest.TestCase):
    def test_a_name_stopped_today_is_not_bought_back_today_but_can_be_tomorrow(self):
        low = np.full((len(DATES), N), 9.9)
        low[1, 0] = 9.0                                        # day 1: the stop at 9.5 is hit
        e = empty()
        e[0] += [(0, 0, 1, 10.0, 9.5, 'brk')]
        e[1] += [(0, 0, 1, 10.0, 9.8, 'brk')]
        e[2] += [(0, 0, 1, 10.0, 9.8, 'brk')]
        got = run(e, px(low=low), no_rebuy_day=True)[0]
        self.assertEqual(got, [('US.S0', '2024-12-30', 1), ('US.S0', '2025-01-02', 1)])
        got = run(e, px(low=low))[0]                          # off: bought back at the same close
        self.assertIn(('US.S0', '2024-12-31', 1), got)

    def test_a_trail_exit_at_the_close_blocks_that_close_too(self):
        c = np.full((len(DATES), N), 10.0)
        c[1, 0] = 11.0
        c[2, 0] = 9.9                                          # closes under the trail line on day 2
        ema = {'t': np.full((len(DATES), N), 10.5)}
        e = empty()
        e[0] += [(0, 0, 1, 10.0, 9.0, 'brk')]
        e[2] += [(0, 0, 1, 9.9, 9.0, 'brk')]
        p = px(close=c, low=np.minimum(c - .1, 9.8), high=c + .1)
        _, _, tr = Y.simulate(p, ema, Y.Rules(**{**RULES, 'trail': 't', 'no_rebuy_day': True}), e, DATES[0],
                              DATES[-1])
        self.assertEqual([(t['entry'], t['why']) for t in tr], [('2024-12-30', 'trail')])

    def test_a_trim_counts_as_a_sale(self):
        e = empty()
        high = np.full((len(DATES), N), 10.1)
        high[1, 0] = 12.0                                      # +4R: the whole position goes at 3R
        e[0] += [(0, 0, 1, 10.0, 9.5, 'brk')]
        e[1] += [(0, 0, 1, 10.0, 9.5, 'brk')]
        got = run(e, px(high=high), trims=(3,), trim_frac=1.0, no_rebuy_day=True)[0]
        self.assertEqual(got, [('US.S0', '2024-12-30', 1)])


class TiersAndGross(unittest.TestCase):
    def test_a_tier_multiplies_the_risk_and_caps_the_name(self):
        e = empty()
        e[0] += [(0, 0, 1, 10.0, 9.5, 'brk', None, None, .45, 2.0), (1, 1, 1, 10.0, 9.5, 'brk', None, None, .5, 4.0)]
        _, tr, _ = run(e)
        w = {t['code']: t['executions'][0]['shares'] * 10.0 for t in tr}
        self.assertAlmostEqual(w['US.S0'], .4)                 # 1% x 2 / 5% stop
        self.assertAlmostEqual(w['US.S1'], .5)                 # 1% x 4 / 5% = 80%, capped at 50%
        self.assertEqual({t['code']: t['tier'] for t in tr}, {'US.S0': 2.0, 'US.S1': 4.0})

    def test_adds_stay_inside_the_entry_cap(self):
        c = np.full((len(DATES), N), 10.0)
        c[1:, 0] = 12.0
        e = empty()
        e[0] += [(0, 0, 1, 10.0, 9.5, 'brk', None, None, .25)]
        p = px(close=c)
        _, tr, _ = run(e, p, add_r=2.0, add_frac=1.0, cap_adds_entry=True)
        add = [x for x in tr[0]['executions'] if x['action'] == 'add']
        # 20% entry worth 24% of a 1.04 equity at the day-1 close: the add only fills the 25% cap
        self.assertAlmostEqual(add[0]['shares'] * 12.0, .25 * 1.04 - .24)
        _, tr2, _ = run(e, p, add_r=2.0, add_frac=1.0)          # off: the add uses the policy cap
        add2 = [x for x in tr2[0]['executions'] if x['action'] == 'add']
        self.assertGreater(add2[0]['shares'], add[0]['shares'])

    def test_gross_room_includes_the_cost_so_no_margin_is_drawn(self):
        e = empty()
        e[0] += [(0, k, 1, 10.0, 9.9, 'brk') for k in range(3)]   # each wants 100% of equity
        kw = dict(buy_cost=.001, margin_rate=.07, max_gross=1.0, max_position=1.0)
        _, _, tr_ = run(e, **kw)
        self.assertGreater(tr_['margin'], 0)                   # off: the cost puts cash below zero
        _, _, tr_ = run(e, gross_cost=True, **kw)
        self.assertEqual(tr_['margin'], 0)
        self.assertLessEqual(max(tr_['gross']), 1.0 + 1e-12)

    def test_a_rising_short_is_covered_at_the_close_back_to_the_gross_limit(self):
        c = np.full((len(DATES), N), 10.0)
        c[2:, 1] = 12.0                                        # the short rises 20% on day 2
        e = empty()
        e[0] += [(0, 0, 1, 10.0, 9.0, 'brk', None, None, .5), (1, 1, -1, 10.0, 15.0, 's_x', None, None, .5)]
        p = px(close=c, high=c + .1, low=c - .1)
        kw = dict(max_gross=1.0, max_position=.5, risk=.5)
        _, tr, tk = run(e, p, **kw)
        self.assertGreater(max(tk['gross']), 1.0)              # off: 50% + 60% on an equity of 0.9
        _, tr, tk = run(e, p, gross_close=True, **kw)
        self.assertLessEqual(max(tk['gross']), 1.0 + 1e-9)
        short = next(t for t in tr if t['side'] < 0)
        self.assertEqual([(x['time'], x['action']) for x in short['executions']][:2],
                         [('2024-12-30', 'entry'), ('2025-01-02', 'gross')])
        self.assertTrue(all(x['action'] != 'gross' for t in tr if t['side'] > 0 for x in t['executions']))

    def test_track_counts_new_and_open(self):
        e = empty()
        e[0] += [(0, 0, 1, 10.0, 9.5, 'brk'), (1, 1, 1, 10.0, 9.5, 'brk')]
        e[2] += [(0, 2, 1, 10.0, 9.5, 'brk')]
        _, _, tr_ = run(e)
        self.assertEqual(tr_['new'], [2, 0, 1, 0])
        self.assertEqual(tr_['open'], [2, 2, 3, 3])

    def test_the_placebo_keeps_the_tier(self):
        e = empty()
        e[0] += [(0, 0, 1, 10.0, 9.5, 'brk', None, None, .5, 3.0)]
        pool = np.zeros((len(DATES), N), bool)
        pool[:, 4] = True
        _, _, tr = Y.simulate(px(), {}, Y.Rules(**RULES), e, DATES[0], DATES[-1], placebo=np.random.default_rng(1),
                              pool=pool)
        self.assertEqual((tr[0]['code'], tr[0]['tier']), ('US.S4', 3.0))


class Fake:
    """Two long entries a day; name 1 is his EP; with daily_cap 'build' the build keeps max_new of them."""
    daily_cap = 'engine'

    def __init__(self, cap='engine'):
        self.daily_cap = cap

    def build(self, A, cfg, trace=None):
        e = [[] for _ in A['days']]
        for d in range(len(A['days'])):
            e[d] += [(0.0, 0, 1, 10.0, 9.5, 'brk'), (1.0, 1, 1, 10.0, 9.0, 'ep')]
        if self.daily_cap == 'build' and cfg.get('max_new'):
            e = [sorted(x, key=lambda q: q[0])[:cfg['max_new']] for x in e]
        rules = Y.Rules(buy_cost=0, sell_cost=0, margin_rate=0, trail='', trims=(), max_gross=2.8, max_open=30,
                        max_position=.6, management_by_kind={'ep': {'max_position': .8}})
        return e, rules, np.zeros((len(A['days']), 2), bool), np.ones((len(A['days']), 2), bool)

    def ep_mask(self, A, cfg):
        return None


def arrays():
    one = np.ones((len(DATES), 2))
    return dict(open=10 * one, high=10.5 * one, low=9.5 * one, close=10 * one, turnover=one, to20=one,
                days=DATES, codes=np.array(['US.A', 'US.B']), market='us')


class Transform(unittest.TestCase):
    def test_without_human_nothing_changes(self):
        A = arrays()
        a = SH.wrap(Fake()).build(A, {})
        b = Fake().build(A, {})
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[1], b[1])

    def test_the_hard_limits_on_the_rules(self):
        r = SH.wrap(Fake()).build(arrays(), {'human': {}})[1]
        self.assertEqual((r.max_gross, r.max_open, r.max_new_all, r.max_new_year, r.max_position),
                         (1.0, 10, 3, 250, .5))
        self.assertTrue(r.no_rebuy_day and r.gross_cost and r.cap_adds_entry)
        self.assertEqual(r.management_by_kind['ep']['max_position'], .5)

    def test_tiers_first_match_and_at_most_three(self):
        A = arrays()
        h = {'tiers': [{'when': ['ep'], 'risk': 3, 'cap': .5}, {'when': ['stop<=0.05'], 'risk': 2, 'cap': .3}],
             'base': {'risk': 1, 'cap': .2}}
        e = SH.wrap(Fake()).build(A, {'human': h})[0]
        self.assertEqual([(x[1], x[8], x[9]) for x in e[0]], [(0, .3, 2.0), (1, .5, 3.0)])
        h['tiers'].append({'when': ['long'], 'risk': 1})
        with self.assertRaises(ValueError):
            SH.wrap(Fake()).build(A, {'human': h})

    def test_a_tier_cap_stays_under_the_study_cap_unless_cap_above(self):
        A = arrays()
        h = {'tiers': [{'when': ['ep'], 'risk': 3, 'cap': .5}]}
        e, r, _, _ = SH.wrap(Fake()).build(A, {'human': h})
        self.assertEqual(r.max_position, .5)                   # the study's .6, cut to the 50% limit
        e, r, _, _ = SH.wrap(Fake()).build(A, {'human': dict(h, cap_above=True)})
        self.assertEqual(r.max_position, .5)
        self.assertEqual([(x[1], x[8], x[9]) for x in e[0]], [(0, .5, None), (1, .5, 3.0)])

        class Low(Fake):
            def build(self, A, cfg, trace=None):
                e, rules, m, p = super().build(A, cfg, trace)
                return e, replace(rules, max_position=.3), m, p
        e, r, _, _ = SH.wrap(Low()).build(A, {'human': h})
        self.assertEqual(r.max_position, .3)                   # without cap_above the tier's 50% cannot apply
        e, r, _, _ = SH.wrap(Low()).build(A, {'human': dict(h, cap_above=True)})
        self.assertEqual(r.max_position, .5)
        self.assertEqual([(x[1], x[8], x[9]) for x in e[0]], [(0, .3, None), (1, .5, 3.0)])
        short = [(0.0, 0, -1, 10.0, 10.5, 'ep')]               # a short never takes a tier with cap_above
        out = H.apply(SH.wrap(Low()), A, {}, dict(h, cap_above=True), [short], replace(r, max_position=.3))[0]
        self.assertEqual(out[0][0][8:], (.3, None))

    def test_near_the_high_uses_the_highs_before_the_day_without_features(self):
        h = np.arange(600, dtype=float).reshape(300, 2)
        h[260, 0] = 1e6                                      # a spike on day 260
        f = H.condition(object(), {'high': h}, {}, 'near52<=0')
        self.assertFalse(f(260, (0, 0, 1, 500.0, 1, 'x')))   # under the prior high (518); the spike is not known yet
        self.assertTrue(f(261, (0, 0, 1, 1e6, 1, 'x')))
        self.assertFalse(f(261, (0, 0, 1, 1e6 - 1, 1, 'x')))
        self.assertFalse(f(100, (0, 0, 1, 1e9, 1, 'x')))     # less than a year of highs: unknown

    def test_engine_cap_builds_uncapped_and_counts_successful_opens(self):
        A = arrays()
        capped = SH.wrap(Fake('build')).build(A, {'max_new': 1, 'human': {}})
        self.assertEqual(len(capped[0][0]), 1)
        self.assertEqual(capped[1].max_new_long, 0)
        e, r, _, _ = SH.wrap(Fake('build')).build(A, {'max_new': 1, 'human': {'engine_cap': True}})
        self.assertEqual(len(e[0]), 2)
        self.assertEqual(r.max_new_long, 1)


if __name__ == '__main__':
    unittest.main()
