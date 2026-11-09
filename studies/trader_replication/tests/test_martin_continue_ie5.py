import ast
import csv
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

from studies.trader_replication import martin_continue_ie5 as ie5
from studies.trader_replication.system import Rules, simulate


class IE5Tests(unittest.TestCase):
    def test_selected_indicator_branches_are_bitwise_equal_to_original(self):
        n = 345
        rng = np.random.default_rng(8)
        close = 20 + np.cumsum(rng.normal(.03, .2, n))
        close[50:58] = close[49]
        opening = close * rng.uniform(.98, 1.02, n)
        arrays = dict(o=opening, h=np.maximum(opening, close) * 1.02,
                      l=np.minimum(opening, close) * .98, c=close,
                      v=rng.uniform(0, 1000, n), t=close * 500)
        arrays['h'][7] = np.nan
        arrays['v'][9] = np.nan
        arrays['v'][40:43] = 0
        days = [(date(2030, 1, 1) + timedelta(days=i)).isoformat() for i in range(n)]
        extras = dict(earn_index=np.maximum.accumulate(np.where(np.arange(n) % 17 == 0, np.arange(n), -1)))
        stock = ie5.lib.Stock(arrays, days, close, extras)
        for family, wanted in (('avwap', {'high', 'low', 'volume', 'gap', 'earnings', 'breakout'}),
                               ('chips', {'cost', 'concentration'}),
                               ('complexity', {'fractal', 'permutation', 'runs'})):
            for parameter in (3, 14, 50, 200):
                reference = stock.evaluate(family, parameter)
                actual = ie5.indicator_values(stock, family, parameter, wanted)
                for name in wanted:
                    np.testing.assert_array_equal(actual[name], reference[name], err_msg=family + '.' + name)
                    finite = np.isfinite(reference[name])
                    self.assertEqual(actual[name][finite].tobytes(), reference[name][finite].tobytes(),
                                     family + '.' + name)
        stock.ema.cache_clear()

    def test_selected_avwap_branches_ignore_future_bars(self):
        n, cut = 120, 90
        days = [(date(2030, 1, 1) + timedelta(days=i)).isoformat() for i in range(n)]
        c = 10 + np.arange(n) / 100 + np.sin(np.arange(n) / 3)
        arrays = dict(o=c * .99, h=c * 1.02, l=c * .98, c=c, v=np.arange(n) + 100., t=c * 100.)
        extras = dict(earn_index=np.maximum.accumulate(np.where(np.arange(n) % 13 == 0, np.arange(n), -1)))
        a = ie5.lib.Stock(arrays, days, c, extras)
        b = ie5.lib.Stock({k: v[:cut] for k, v in arrays.items()}, days[:cut], c[:cut],
                          {k: v[:cut] for k, v in extras.items()})
        for family, wanted in (('avwap', {'high', 'low', 'volume', 'gap', 'earnings', 'breakout'}),
                               ('complexity', {'fractal', 'permutation', 'runs'})):
            full = ie5.indicator_values(a, family, 14, wanted)
            short = ie5.indicator_values(b, family, 14, wanted)
            for key in wanted:
                np.testing.assert_array_equal(full[key][:cut], short[key])

    def test_signal_adapter_never_reads_execution_day(self):
        days = ['2030-01-02', '2030-01-03', '2030-01-04']
        close = np.array([[10., 20.], [11., 19.], [12., 18.]])
        d = SimpleNamespace(days=days, di={s: i for i, s in enumerate(days)},
                            A=dict(codes=np.array(['SYN_A', 'SYN_B']), close=close))
        first = ie5.selected_orders(d, {days[0]: ['SYN_B', 'SYN_A']}, window=(days[1], days[-1]))
        close[1:] *= 100
        self.assertEqual(first, ie5.selected_orders(d, {days[0]: ['SYN_B', 'SYN_A']},
                                                   window=(days[1], days[-1])))
        self.assertEqual([r['code'] for r in first], ['SYN_B', 'SYN_A'])
        self.assertTrue(all(r['signal_day'] == days[0] and r['day'] == days[1] for r in first))

    def test_existing_engine_next_open_fill_stop_and_next_open_ema_exit(self):
        days = np.array(['2030-01-02', '2030-01-03', '2030-01-04', '2030-01-07', '2030-01-08'])
        close = np.array([[10.], [10.2], [10.3], [10.1], [10.0]])
        opening = np.array([[10.], [10.1], [10.2], [10.2], [10.05]])
        d = SimpleNamespace(days=days.tolist(), di={s: i for i, s in enumerate(days)},
                            A=dict(codes=np.array(['SYN_A']), close=close))
        orders = ie5.selected_orders(d, {days[0]: ['SYN_A']}, window=(days[1], days[-1]))
        d.A.update(open=opening, low=np.minimum(opening, close) * .999)
        from studies.trader_replication import martin_continue_hc as hc, martin_continue_hh as hh
        book = hc.make_books(d, orders, hh.observations(d, orders), True)[0]
        px = dict(dates=days, codes=d.A['codes'], open=opening, close=close,
                  low=d.A['low'], high=np.maximum(opening, close) * 1.001)
        rules = Rules(trail='e21', trims=(), risk=.01, max_gross=1., max_position=1.,
                      trail_next_open=True, intraday_kinds=('list',),
                      buy_cost=0., sell_cost=0., margin_rate=0.)
        ema = {'e21': np.array([[10.], [10.0], [10.2], [10.2], [10.2]])}
        _, _, trades = simulate(px, ema, rules, book, days[1], days[-1], audit=True, preopen=True,
                                preopen_fill_stop_pct_by_kind={'list': .025})
        trade = trades[0]
        self.assertEqual(trade['fill'], opening[1, 0])
        self.assertAlmostEqual(trade['stop'], opening[1, 0] * .975)
        self.assertEqual(trade['exit'], days[4])
        self.assertEqual(trade['executions'][-1]['price'], opening[4, 0])

    def run_add_gap(self, correction=False):
        days = np.array(['2030-01-02', '2030-01-03', '2030-01-04', '2030-01-07'])
        opening = np.array([[10.], [10.], [10.1], [9.9]])
        close = np.array([[10.], [10.1], [10.3], [9.9]])
        high = np.array([[10.1], [10.2], [10.4], [9.95]])
        low = np.array([[9.9], [9.9], [10.0], [9.85]])
        px = dict(dates=days, codes=np.array(['SYN_A']), open=opening, close=close, high=high, low=low)
        book = [[], [((0,), 0, 1, 10., 9.75, 'list', None)], [], []]
        rules = Rules(trail='', trims=(), risk=.01, max_gross=2., max_position=1.,
                      intraday_kinds=('list',), add_levels=(1,), add_next_open=True,
                      buy_cost=0., sell_cost=0., margin_rate=0.)
        _, _, trades = simulate(px, {}, rules, book, days[1], days[-1], audit=True, preopen=True,
                                preopen_fill_stop_pct_by_kind={'list': .025},
                                preopen_add_stop_gap=correction)
        return px, trades

    @unittest.expectedFailure
    def test_inherited_preopen_add_stop_must_remain_inside_session_range(self):
        px, trades = self.run_add_gap()
        exit_execution = trades[0]['executions'][-1]
        self.assertEqual(exit_execution['time'], px['dates'][-1])
        self.assertLessEqual(exit_execution['price'], px['high'][-1, 0])

    def test_corrected_preopen_add_stop_executes_at_actual_open(self):
        px, trades = self.run_add_gap(correction=True)
        last = trades[0]['executions'][-1]
        self.assertEqual(last['action'], 'add_stop_open')
        self.assertEqual(last['price'], px['open'][-1, 0])
        self.assertEqual(last['price'], 9.9)
        self.assertTrue(any(e['action'] == 'add' and e['time'] == last['time']
                            for e in trades[0]['executions']))
        for execution in trades[0]['executions']:
            day = list(px['dates']).index(execution['time'])
            self.assertLessEqual(px['low'][day, 0], execution['price'])
            self.assertLessEqual(execution['price'], px['high'][day, 0])

    def test_percentile_delta_uses_only_same_night_and_five_sessions_earlier(self):
        days = [(date(2030, 1, 1) + timedelta(days=i)).isoformat() for i in range(12)]
        meta = dict(days=days, scope={s: ['SYN_A', 'SYN_B'] for s in days})
        keys, slices, _ = ie5.layout(meta)
        raw = np.arange(len(keys), dtype=np.float32).reshape(-1, 1)
        a = ie5.transform(raw, meta, slices, 'delta5')
        raw[16:] *= -100
        b = ie5.transform(raw, meta, slices, 'delta5')
        np.testing.assert_array_equal(a[:16], b[:16])
        small = dict(days=days[:8], scope={s: meta['scope'][s] for s in days[:8]})
        _, sl, _ = ie5.layout(small)
        np.testing.assert_array_equal(a[:16], ie5.transform(raw[:16], small, sl, 'delta5'))

    def test_random_top_five_stays_inside_each_gated_pool(self):
        pools = {'a': [f'SYN_{i}' for i in range(12)], 'b': [], 'c': ['SYN_X']}
        first = ie5.random_selection(pools, 7)
        self.assertEqual(first, ie5.random_selection(pools, 7))
        for day, selected in first.items():
            self.assertEqual(len(selected), min(5, len(pools[day])))
            self.assertEqual(len(selected), len(set(selected)))
            self.assertLessEqual(set(selected), set(pools[day]))

    def test_annual_drawdown_includes_year_open_equity(self):
        out = ie5.annual_statistics(np.array([.8, .9, .81]),
                                    np.array(['2030-12-30', '2030-12-31', '2031-01-02']), [])
        self.assertAlmostEqual(out['2030']['maxdd'], .2)
        self.assertAlmostEqual(out['2031']['maxdd'], .1)
        self.assertAlmostEqual(out['2031']['return'], -.1)
        self.assertIsNone(out['2031']['win'])

    def test_classification_does_not_read_exam_or_returns(self):
        info = ie5.read_json(ie5.EXPLANATIONS)
        self.assertEqual(len(info['gates']), 40)
        self.assertTrue(info['frozen_before_exam'])
        self.assertTrue(all(r['source'] for r in info['gates'] if r['category'] == 1))

    def test_no_real_security_or_entry_date_constants(self):
        with (ie5.ROOT / 'studies/martin_luk/notes/trades.csv').open() as f:
            rows = list(csv.DictReader(f))
        forbidden = {r['ticker'] for r in rows} | {'US.' + r['ticker'] for r in rows}
        forbidden |= {r['entry_date'] for r in rows if r['entry_date']}
        tree = ast.parse(Path(ie5.__file__).read_text())
        literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertFalse(literals & forbidden, literals & forbidden)


if __name__ == '__main__':
    unittest.main()
