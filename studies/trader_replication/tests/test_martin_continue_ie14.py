import ast
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie14 as m


class IE14Tests(unittest.TestCase):
    def test_features_do_not_read_after_the_signal_close(self):
        t = np.arange(320)
        c = 30 + t / 40 + np.sin(t / 3)
        arrays = dict(c=c, o=c * .998, h=c * 1.025, l=c * .975, v=1000. + t, t=(1000. + t) * c)
        full = m.features(arrays)
        for cut in (95, 200, 290):
            truncated = m.features({k: a[:cut] for k, a in arrays.items()})
            changed = {k: a.copy() for k, a in arrays.items()}
            for a in changed.values():
                a[cut:] *= 30
            future = m.features(changed)
            for name in full:
                np.testing.assert_array_equal(full[name][:cut], truncated[name], err_msg=name)
                np.testing.assert_array_equal(full[name][:cut], future[name][:cut], err_msg=name)

    def fixture(self):
        days = np.array(['2030-01-02', '2030-01-03', '2030-01-04', '2030-01-07', '2030-01-08'])
        c = np.array([100, 102, 104, 101, 98.], float)[:, None]
        px = dict(open=c.copy(), high=c * 1.01, low=c * .99, close=c.copy(), dates=days,
                  codes=np.array(['SYNTHETIC']))
        ema = dict(e9=np.full_like(c, 102.), gate=np.ones_like(c, bool))
        book = [[(0, 0, 1, 100., 97., 'test')], [], [], [], []]
        rule = m.system.Rules(trail='e9', trims=(), buy_cost=0, sell_cost=0, margin_rate=0,
                              arm_trail_on_entry=True, trail_next_open=True, intraday_kinds=('test',))
        return px, ema, book, rule

    def test_order_requires_the_next_day_high_to_cross_the_known_level(self):
        px, _, _, _ = self.fixture()
        px['high'][0, 0] = 102
        d = SimpleNamespace(px=px, f=dict(adr=np.full_like(px['close'], 6.), money=np.full_like(px['close'], 2e8),
                                          e9=np.full_like(px['close'], 100.)))
        px['high'][1, 0] = 102
        self.assertIsNone(m.order(1, 0, 1, d, m.BASE))
        px['high'][1, 0] = 103
        e = m.order(1, 0, 1, d, m.BASE)
        self.assertEqual(e[3], 102)
        self.assertGreater(e[4], 0)
        before = e[:6]
        px['low'][2:, 0] = 1
        self.assertEqual(before, m.order(1, 0, 1, d, m.BASE)[:6])

    def test_same_day_stop_wins_over_any_profit_level(self):
        px, ema, book, rule = self.fixture()
        px['high'][0, 0] = 130
        px['low'][0, 0] = 90
        book[0][0] += (97.,)
        curve, dates, trades = m.system.simulate(px, ema, replace(rule, trims=(3, 5)), book,
                                                  str(px['dates'][0]), str(px['dates'][-1]), audit=True)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]['why'], 'stop_day0')
        self.assertEqual([x['action'] for x in trades[0]['executions']], ['entry', 'stop_day0'])

    def test_short_stop_uses_the_signal_high_without_an_invented_cap(self):
        px, _, _, _ = self.fixture()
        px['high'][0, 0] = 110.
        px['low'][0, 0] = 95.
        px['open'][1, 0] = 90.
        px['low'][1, 0] = 85.
        d = SimpleNamespace(px=px, f=dict(adr=np.full_like(px['close'], 6.), money=np.full_like(px['close'], 2e8),
                                          e9=np.full_like(px['close'], 100.)))
        e = m.order(1, 0, -1, d, m.BASE, 'short')
        self.assertEqual(e[3], 90.)
        self.assertAlmostEqual(e[4], 110.)

    def test_close_cross_executes_at_the_following_open(self):
        px, ema, book, rule = self.fixture()
        ema['e9'][:, 0] = [99, 101, 103, 102, 99]
        px['low'][:, 0] = px['open'][:, 0] - .1
        curve, days, trades = m.system.simulate(px, ema, rule, book, str(px['dates'][0]), str(px['dates'][-1]), audit=True)
        self.assertEqual(trades[0]['trail_signal'], str(px['dates'][3]))
        self.assertEqual(trades[0]['exit'], str(px['dates'][4]))
        self.assertEqual(trades[0]['executions'][-1]['price'], px['open'][4, 0])

    def test_r_add_needs_a_fresh_setup_and_waits_for_the_next_open(self):
        px, ema, book, rule = self.fixture()
        px['open'][:, 0] = [100, 104, 106, 108, 109]
        px['close'][:, 0] = [100, 104, 106, 108, 109]
        px['high'][:, 0] = px['close'][:, 0] + .1
        px['low'][:, 0] = px['close'][:, 0] - .1
        ema['gate'][:, 0] = [False, False, True, False, False]
        rule = replace(rule, trail='', add_r=1, add_frac=.5, add_filter='gate', add_next_open=True,
                       max_position=.8, max_gross=2)
        _, _, trades = m.system.simulate(px, ema, rule, book, str(px['dates'][0]), str(px['dates'][-1]), audit=True)
        adds = [x for x in trades[0]['executions'] if x['action'] == 'add']
        self.assertEqual(len(adds), 1)
        self.assertEqual(adds[0]['time'], str(px['dates'][3]))
        self.assertEqual(adds[0]['price'], px['open'][3, 0])

    def test_one_fill_cannot_cover_two_human_attempts(self):
        labels = [dict(id=str(i), code='SYNTHETIC', side=1, lo=2, hi=4, anchor=3) for i in range(2)]
        events = [dict(code='SYNTHETIC', side=1, t=3)]
        self.assertEqual(len(m.match(labels, events)), 1)
        events += [dict(code='SYNTHETIC', side=1, t=4)]
        self.assertEqual(len(m.match(labels, events)), 2)

    def test_profitable_short_timed_cover_waits_for_the_following_open(self):
        px, ema, book, rule = self.fixture()
        px['open'][:, 0] = [100, 98, 96, 94, 93]
        px['close'][:, 0] = px['open'][:, 0]
        px['high'][:, 0] = px['open'][:, 0] + .1
        px['low'][:, 0] = px['open'][:, 0] - .1
        book[0][0] = (0, 0, -1, 100., 103., 'test')
        rule = replace(rule, trail='', short_trim_day=2, short_trim_day_frac=.5, short_trim_next_open=True)
        _, _, trades = m.system.simulate(px, ema, rule, book, str(px['dates'][0]), str(px['dates'][-1]), audit=True)
        partial = [x for x in trades[0]['executions'] if x['action'] == 'day_trim_open']
        self.assertEqual(len(partial), 1)
        self.assertEqual(partial[0]['time'], str(px['dates'][3]))
        self.assertEqual(partial[0]['price'], px['open'][3, 0])

    def test_matching_reassigns_flexible_window_to_preserve_exact_window(self):
        labels = [dict(id='a', code='SYNTHETIC', side=1, lo=2, hi=4, anchor=3),
                  dict(id='b', code='SYNTHETIC', side=1, lo=3, hi=3, anchor=3)]
        events = [dict(code='SYNTHETIC', side=1, t=3), dict(code='SYNTHETIC', side=1, t=4)]
        match = m.match(labels, events)
        self.assertEqual(match, {'b': 0, 'a': 1})

    def test_rules_have_no_signal_or_daily_trade_quota(self):
        rules = m.policy(m.BASE)
        self.assertEqual((rules.max_new_all, rules.max_new_long, rules.max_new_year), (0, 0, 0))
        self.assertEqual(rules.max_open, 4)

    def test_a_rejected_candidate_is_not_registered_again(self):
        metrics = dict(funnel={'没信号': 50, '没仓位': 20}, no_signal={'股票池': 30, '领涨': 10})
        seen = {m.key(m.BASE)}
        previous = set()
        for round_number in range(2, 8):
            layer, candidates = m.proposals(m.BASE, metrics, round_number, seen)
            self.assertLessEqual(len(candidates), 5)
            keys = {m.key(c) for c in candidates}
            self.assertFalse(keys & previous)
            seen |= keys
            previous |= keys

    def test_holdout_purges_both_label_windows_and_forward_price_horizons(self):
        days = ['2030-06-27', '2030-06-28', '2030-07-01', '2030-07-02']
        labels = [dict(id='prior', half='2030H1', lo=0, hi=1, anchor=0),
                  dict(id='held', half='2030H2', lo=2, hi=3, anchor=2)]
        with patch.object(m, 'read', return_value=dict(days=days)):
            self.assertEqual(m.training_rows(labels, '2030H2'), [])
            self.assertEqual(m.training_rows(labels, '2030H1'), [labels[1]])

    def test_every_candidate_matches_only_training_labels(self):
        labels = [dict(id='train'), dict(id='held')]
        metric = dict(weighted_coverage=0., capture=0., rank=[0.,0.,0.], ids=['train'], bought=0, closed=0, n=1)
        observed = []
        def score(data, cfg, account, rows):
            observed.append([r['id'] for r in rows])
            return {}
        with patch.object(m, 'WORK', Path('NONEXISTENT_SYNTHETIC_IE14')), \
             patch.object(m, 'training_rows', return_value=labels[:1]), \
             patch.object(m, 'run_account', return_value=dict(id='synthetic_account')), \
             patch.object(m, 'score', side_effect=score), \
             patch.object(m, 'selection', return_value=metric), \
             patch.object(m, 'proposals', return_value=('test', [dict(m.BASE, priority='quiet')])), \
             patch.object(m, 'save'), patch('builtins.print'):
            m.search(None, labels, 'synthetic', held='2030H2')
        self.assertEqual(observed, [['train']] * 7)

    def test_full_signal_book_and_execution_fields_are_prefix_causal(self):
        n = 180
        days = np.arange(np.datetime64('2030-01-01'), np.datetime64('2030-01-01') + n).astype(str).tolist()
        t = np.arange(n)
        c = 100 + t / 4 + np.sin(t / 3)
        arrays = dict(o=c * .995, c=c, h=c * 1.04, l=c * .96, v=np.ones(n) * 3e6,
                      t=np.ones(n) * 3e8)
        def data(limit):
            a = {k:v[:limit] for k,v in arrays.items()}
            values = m.features(a, days[:limit])
            values.update(peer=np.ones(limit) * .05, ie8=np.ones(limit))
            f = {k:np.array(v)[:,None] for k,v in values.items()}
            benchmark = dict(close=a['c'].tolist(), e9=values['e9'].tolist(),
                             e21=values['e21'].tolist(), e50=values['e50'].tolist())
            return SimpleNamespace(days=days[:limit], codes=['SYNTHETIC'], start=60, end=limit,
                f=f, built={}, meta=dict(benchmark=[benchmark,benchmark]),
                px={name:a[k][:,None] for name,k in (('open','o'),('high','h'),('low','l'),('close','c'))})
        with patch.object(m.ledger,'load',side_effect=AssertionError('prediction cannot read human labels')), \
             patch.object(m,'labels',side_effect=AssertionError('prediction cannot read human labels')):
            full = m.build(data(n), m.BASE)
        for cut in (95, 150):
            short = m.build(data(cut), m.BASE)
            self.assertEqual(full['book'][:2*cut], short['book'])
            np.testing.assert_array_equal(full['signals']['long'][:cut], short['signals']['long'])

    def test_main_capture_keeps_losses_and_profit_above_the_label_space(self):
        row = dict(signal=True, bought=True, closed=True, space=1., washed=False, stage='卖早卖晚',
                   weight_kind='published_r', weight=1., capture_raw=-.5, capture_clip=0.)
        other = dict(row, weight=3., capture_raw=2., capture_clip=1.)
        summary = m.card_summary([row, other])
        self.assertEqual(summary['capture'], 1.375)
        self.assertEqual(summary['capture_clipped'], .75)
        self.assertEqual(m.card_summary([row])['capture'], -.5)

    def test_zero_profit_weight_does_not_allow_fewer_actual_buys_or_sales(self):
        reference = dict(bought=5, closed=5, weighted_coverage=.4, capture=.2)
        self.assertFalse(m.preserves_replication(reference, dict(reference,bought=4)))
        self.assertFalse(m.preserves_replication(reference, dict(reference,closed=4)))
        self.assertTrue(m.preserves_replication(reference, dict(reference,bought=6)))

    def test_short_hard_deadline_executes_before_a_later_trail_open(self):
        n = 14
        days = np.arange(np.datetime64('2030-03-01'), np.datetime64('2030-03-01')+n).astype(str)
        c = np.full((n,1),90.)
        c[0] = 100.
        c[10] = 96.
        px = dict(open=c.copy(), high=c+.1, low=c-.1, close=c.copy(), dates=days, codes=np.array(['SYNTHETIC']))
        ema = dict(e9=np.full_like(c,95.))
        book = [[(0,0,-1,100.,110.,'test')]] + [[] for _ in range(n-1)]
        rules=m.system.Rules(trail='e9', trail_next_open=True, arm_trail_on_entry=True, short_max_days=10,
                             max_days_next_open=True, trims=(), short_trims=(), intraday_kinds=('test',),
                             buy_cost=0,sell_cost=0,margin_rate=0)
        _,_,trades=m.system.simulate(px,ema,rules,book,str(days[0]),str(days[-1]),audit=True)
        self.assertEqual(trades[0]['days'],10)
        self.assertEqual(trades[0]['why'],'time_open')
        self.assertEqual(trades[0]['executions'][-1]['price'],px['open'][10,0])
        _,_,legacy=m.system.simulate(px,ema,replace(rules,max_days_next_open=False),book,
                                    str(days[0]),str(days[-1]),audit=True)
        self.assertEqual(legacy[0]['days'],11)

    def test_first_fifty_ema_retest_does_not_expire_with_the_holding_deadline(self):
        c=np.full(180,100.);c[100:]=95.
        line=m.lib.smooth(c,50)
        h=c*1.001;h[125:127]=line[125:127]*1.01
        arrays=dict(c=c,o=c,h=h,l=c*.999,v=np.ones(180)*1e6,t=c*1e6)
        values=m.features(arrays)
        self.assertTrue(values['short50'][125])
        self.assertFalse(values['short50'][126])

    def test_human_ticket_diagnostic_cannot_attribute_a_miss_to_bypassed_market_filter(self):
        day='2030-01-02'
        d=SimpleNamespace(days=[day],codes=['SYNTHETIC'],ci={'SYNTHETIC':0},di={day:0},start=0)
        row=dict(id='synthetic',code='SYNTHETIC',side=1,anchor=0,lo=0,hi=0,half='2030H1',
                 entry_date=day,note='',weight=1.,weight_kind='price_proxy',space=1.,precision='exact',
                 mistake=False,group='other')
        b=dict(signals={'long':np.ones((1,1),bool),'short':np.zeros((1,1),bool)},market=np.array([False]))
        with patch.object(m,'build',return_value=b),patch.object(m,'match',return_value={}):
            card=m.score(d,m.BASE,dict(id='synthetic',trades=[]),[row],supplied=True)
        self.assertEqual(card['rows'][0]['stage'],'没仓位')

    def test_no_human_security_or_date_constants_in_implementation(self):
        rows = m.ledger.load(m.LEDGER)
        forbidden = {r.ticker for r in rows} | {'US.' + r.ticker for r in rows}
        forbidden |= {r.entry_date for r in rows if r.entry_date}
        source = Path(m.__file__).read_text()
        strings = {n.value for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertFalse(strings & forbidden)


if __name__ == '__main__':
    unittest.main()
