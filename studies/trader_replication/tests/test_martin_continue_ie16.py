import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

from studies.trader_replication import martin_continue_ie16 as m


class IE16Tests(unittest.TestCase):
    def order_data(self):
        close = np.array([[105.], [104.], [106.]])
        px = dict(open=np.array([[100.], [100.], [105.]]), high=close + 5,
                  low=np.full_like(close, 99.), close=close.copy())
        f = dict(adr=np.full_like(close, 6.), money=np.full_like(close, 2e8),
                 e9=np.full_like(close, 101.), e21=np.full_like(close, 100.),
                 pullback=np.ones_like(close))
        return SimpleNamespace(px=px, f=f)

    def test_market_any_and_both_have_the_stated_meaning(self):
        a = dict(close=[12, 8, 8], e9=[10] * 3, e21=[10] * 3)
        b = dict(close=[8, 12, 8], e9=[10] * 3, e21=[10] * 3)
        self.assertEqual(m.market_mask([a, b], 'both21').tolist(), [False] * 3)
        self.assertEqual(m.market_mask([a, b], 'either21').tolist(), [True, True, False])
        self.assertTrue(m.market_mask([a, b], 'feedback').all())
        # A 50 EMA must be calculated from the available prefix only.
        a = dict(close=[10, 12, 8], e9=[10] * 3, e21=[10] * 3)
        self.assertEqual(m.market_mask([a, a], 'either50').tolist(), [True, True, False])

    def test_market_decisions_ignore_future_index_values(self):
        x = np.arange(90.)
        close = 30 + np.sin(x) + x / 100
        benchmarks = [dict(close=close, e9=m.old.lib.smooth(close, 9),
                           e21=m.old.lib.smooth(close, 21))] * 2
        for mode in m.MARKETS:
            full = m.market_mask(benchmarks, mode)
            prefix = [{k: v[:60] for k, v in b.items()} for b in benchmarks]
            changed = [{k: v.copy() for k, v in b.items()} for b in benchmarks]
            for b in changed:
                for v in b.values():
                    v[60:] *= 100
            np.testing.assert_array_equal(full[:60], m.market_mask(prefix, mode))
            np.testing.assert_array_equal(full[:60], m.market_mask(changed, mode)[:60])

    def test_gap_above_previous_high_was_already_supported(self):
        d = self.order_data()
        d.px['open'][1, 0] = 112
        d.px['high'][1, 0] = 113
        event = m.order(1, 0, d, m.BASE)
        self.assertEqual(event[3], 112)
        self.assertEqual(event, m.old.order(1, 0, 1, d, m.FIXED))

    def test_pullback_levels_are_known_before_the_execution_day(self):
        d = self.order_data()
        d.px['high'][1, 0] = 106
        self.assertIsNone(m.order(1, 0, d, m.BASE))
        for trigger, fill in (('pull_body', 105.), ('pull_close', 105.),
                              ('pull_ema9', 101.), ('pull_ema21', 100.)):
            cfg = dict(m.BASE, trigger=trigger)
            before = m.order(1, 0, d, cfg)
            self.assertEqual(before[3], fill)
            d.px['close'][1:, 0] = 900
            d.px['low'][1:, 0] = 1
            d.f['money'][1:, 0] *= 10
            d.f['adr'][1:, 0] *= 10
            self.assertEqual(before[:6], m.order(1, 0, d, cfg)[:6])
            self.assertEqual(before[8], m.order(1, 0, d, cfg)[8])
        d.f['pullback'][0, 0] = 0
        self.assertIsNone(m.order(1, 0, d, dict(m.BASE, trigger='pull_body')))

    def test_a_touch_without_a_cross_cannot_trigger_a_new_pullback_entry(self):
        d = self.order_data()
        cfg = dict(m.BASE, trigger='pull_body')
        d.px['high'][1, 0] = 105
        self.assertIsNone(m.order(1, 0, d, cfg))
        d.px['high'][1, 0] = 105.1
        self.assertEqual(m.order(1, 0, d, cfg)[3], 105)

    def test_extended_body_trigger_preserves_the_original_stop_and_position_cap(self):
        for adr in (1., 4., 12.):
            for low in (95., 104.8):
                for money in (2e6, 8e8):
                    d = self.order_data()
                    d.f['adr'][0, 0], d.f['money'][0, 0] = adr, money
                    d.px['low'][0, 0] = low
                    event = m.order(1, 0, d, dict(m.BASE, trigger='pull_body'))
                    original = m.old.order(1, 0, 1, d, dict(m.FIXED, trigger='body'))
                    self.assertEqual(event, original)

    def test_same_day_stop_precedes_profit_on_the_extended_trigger(self):
        d = self.order_data()
        d.px.update(dates=np.busday_offset('2030-01-01', np.arange(3)).astype(str),
                    codes=np.array(['SYNTHETIC']))
        d.px['high'][1, 0], d.px['low'][1, 0] = 130, 90
        event = m.order(1, 0, d, dict(m.BASE, trigger='pull_body'))
        rules = m.old.system.Rules(trail='', trims=(3, 5), buy_cost=0, sell_cost=0,
                                   margin_rate=0, intraday_kinds=('long',))
        _, _, trades = m.old.system.simulate(d.px, {}, rules, [[], [event], []],
            str(d.px['dates'][0]), str(d.px['dates'][-1]), audit=True)
        self.assertEqual(trades[0]['why'], 'stop_day0')
        self.assertEqual([x['action'] for x in trades[0]['executions']], ['entry', 'stop_day0'])

    def test_original_pool_thresholds_become_priority_in_the_soft_pool(self):
        cfg = dict(m.BASE, pool='soft_both')
        priority = m.priorities(cfg, np.zeros(3, bool), np.zeros(3),
                                np.array([2e9, 3e7, 2e6]), np.array([4., 6., 6.]))
        self.assertLess(priority[1], priority[0])
        self.assertLess(priority[1], priority[2])

    def test_priority_uses_only_the_supplied_signal_names(self):
        args = (np.array([True, False, False]), np.array([0, 5, 2]),
                np.array([2e7, 2e9, 3e8]), np.array([6., 4., 8.]))
        for priority in m.PRIORITIES:
            cfg = dict(m.BASE, priority=priority, pool='soft_both')
            full = m.priorities(cfg, *args)
            ix = np.array([0, 2])
            self.assertEqual(m.priorities(cfg, *(a[ix] for a in args)), [full[j] for j in ix])
        cfg = dict(m.BASE, priority='upgrade_cluster')
        p = m.priorities(cfg, *args)
        self.assertLess(p[0], p[1])

    def synthetic(self, cut=150, change=None):
        days = np.busday_offset('2030-01-01', np.arange(cut)).astype(str)
        t, j = np.arange(cut)[:, None], np.arange(6)[None, :]
        close = 30 + t * (.02 + j / 100) + np.sin(t / (2 + j))
        px = dict(close=close, open=close * (1 + .04 * np.sin(t + j)), high=close * 1.06,
                  low=close * .94)
        volume = 10000 + 1000 * np.cos(t + j)
        money = np.broadcast_to(np.array([3e6, 15e6, 30e6, 2e8, 5e8, 2e9]), close.shape).copy()
        if change is not None:
            for a in (*px.values(), volume, money):
                a[change:] *= 100
        features = [m.old.features(dict(c=px['close'][:, j], o=px['open'][:, j], h=px['high'][:, j],
                    l=px['low'][:, j], v=volume[:, j], t=money[:, j]), days) for j in range(close.shape[1])]
        f = {k: np.column_stack([a[k] for a in features]) for k in features[0]}
        ranks = m.previous.scan_ranks(px['close'], px['open'], volume, f['money'], f['adr'], days)
        weekly = np.column_stack([m.previous.weekly_line(px['close'][:, j], days) for j in range(close.shape[1])])
        grade, upgrade = m.previous.grades(px['close'], f['e9'], f['e21'], f['e50'], weekly)
        extra = dict(**ranks, weekly21=weekly, grade=grade, upgrade=upgrade,
                     peers=np.full((*close.shape, 5), -1, np.int16))
        benchmark = dict(close=px['close'][:, 0], e9=f['e9'][:, 0], e21=f['e21'][:, 0])
        return SimpleNamespace(px=px, f=f, extra=extra, meta=dict(benchmark=[benchmark] * 2),
            days=days, codes=list(range(close.shape[1])), start=25, end=len(days), latest=None, built={})

    def test_full_selection_and_order_pipeline_does_not_read_future_rows(self):
        configs = [m.BASE, dict(m.BASE, pool='soft_both', market='either50', trigger='pull_body',
                                watch='premier', priority='upgrade_cluster'),
                   dict(m.BASE, pool='soft_money', market='feedback', trigger='pull_ema9',
                         watch='fresh', priority='adr_upgrade')]
        for cfg in configs:
            full = m.build(self.synthetic(), cfg)
            for other in (self.synthetic(cut=100), self.synthetic(change=100)):
                result = m.build(other, cfg)
                for name in ('pool', 'market', 'watched', 'triggers'):
                    stop = 99 if name == 'triggers' else 100
                    np.testing.assert_array_equal(full[name][:stop], result[name][:stop])
                np.testing.assert_array_equal(full['signals']['long'][:100], result['signals']['long'][:100])
                self.assertEqual(full['book'][:200], result['book'][:200])

    def test_rounds_change_one_selection_field_and_never_repeat_a_configuration(self):
        cfg, seen = dict(m.BASE), {m.old.key(m.BASE)}
        for number in range(1, 7):
            layer, candidates = m.proposals(cfg, {'市况': 20, '股票池': 15}, seen, number)
            self.assertTrue(candidates)
            self.assertLessEqual(len(candidates), 5)
            for candidate in candidates:
                self.assertEqual([k for k in cfg if candidate[k] != cfg[k]], [layer])
                self.assertNotIn(m.old.key(candidate), seen)
                seen.add(m.old.key(candidate))
            cfg = candidates[0]
        self.assertEqual(m.previous.WORK.name, 'ie15_work')
        self.assertIsNot(m.previous.build, m.build)

    def test_source_contains_no_human_stock_or_entry_date_literals(self):
        labels = m.old.ledger.load(m.old.LEDGER)
        forbidden = {r.ticker for r in labels} | {'US.' + r.ticker for r in labels}
        forbidden |= {r.entry_date for r in labels if r.entry_date}
        for path in (Path(m.__file__), Path(__file__), *m.WORK.glob('*.py')):
            literals = {n.value for n in ast.walk(ast.parse(path.read_text()))
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            self.assertFalse(literals & forbidden, path.name)


if __name__ == '__main__':
    unittest.main()
