import unittest
from types import SimpleNamespace
import numpy as np
from studies.trader_replication import martin_continue_fq as fq, system
from studies.trader_replication.martin_continue_b_check import digest


class ElevenPositionTraceTests(unittest.TestCase):
    def test_trace_distinguishes_kinds_and_captures_real_slot_limit(self):
        days = ['2024-01-02', '2024-01-03']
        a = np.full((2, 2), 10.)
        px = {'open': a.copy(), 'high': a.copy(), 'low': a.copy(), 'close': a.copy(),
              'dates': np.array(days), 'codes': np.array(['A', 'B'])}
        d = SimpleNamespace(days=days, A=px, pool=None,
                            base=SimpleNamespace(px=lambda _: px, ema_inputs=lambda *_: {}))
        book = [[(0, 0, 1, 10., 9., 'n1'), (1, 1, 1, 10., 9., 'list')],
                [(0, 0, 1, 10., 9., 'list')]]
        rules = system.Rules(trail='', trims=(), max_open=1, buy_cost=0, sell_cost=0, margin_rate=0,
                             intraday_kinds=('n1', 'list'))
        _, _, trades = system.simulate(px, {}, rules, book, days[0], days[-1], audit=True)
        trace = fq.trace_orders(d, book, rules, digest(trades))
        records = {(r['day'], r['kind'], r['code']): r for r in trace['orders']}
        self.assertEqual(records[(days[0], 'n1', 'A')]['reason'], 'opened')
        self.assertIn('rules.max_open', records[(days[0], 'list', 'B')]['reason'])
        self.assertIn('j in pos', records[(days[1], 'list', 'A')]['reason'])
        self.assertEqual(trace['years']['2024']['max_positions_after_open'], 1)


if __name__ == '__main__':
    unittest.main()
