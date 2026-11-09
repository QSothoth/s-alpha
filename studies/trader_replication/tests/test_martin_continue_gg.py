import unittest
from types import SimpleNamespace
import numpy as np
from studies.trader_replication import system
from studies.trader_replication.martin_continue_gg import holding_missing, run


class ReentryTest(unittest.TestCase):
    def fixture(self):
        days = ['2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07']
        bars = np.array([(100., 101., 98., 100.), (96., 97., 95., 96.),
                         (100., 101., 97., 100.), (100., 101., 99., 100.)])
        A = {key: bars[:, i:i + 1] for i, key in enumerate(('open', 'high', 'low', 'close'))}
        A['codes'] = np.array(['US.A'])
        px = dict(A, dates=np.array(days))
        base = SimpleNamespace(px=lambda _: px, ema_inputs=lambda *_: {})
        d = SimpleNamespace(A=A, days=days, di={day: i for i, day in enumerate(days)}, base=base, pool=None)
        rules = system.Rules(trail='', trims=(), risk=.05, max_position=1 / 6, max_gross=1.,
                             buy_cost=0., sell_cost=0., margin_rate=0., no_rebuy_day=True,
                             intraday_kinds=('n1',))
        return d, px, rules

    def test_open_exit_cannot_rebuy_same_open_but_can_reenter_next_day(self):
        d, px, rules = self.fixture()
        result = run(d, 0, 0, [1, 2], rules, px, {}, True)
        self.assertEqual([(t['entry'], t['exit'], t['why']) for t in result['trades']],
                         [('2025-01-02', '2025-01-03', 'gap_stop'),
                          ('2025-01-06', '2025-01-06', 'stop_day0')])
        self.assertEqual(result['additional_entries'], 1)
        self.assertIn('no_rebuy_day', result['order_trace'][1]['reason'])

    def test_missing_holding_bar_is_recorded(self):
        d, _, _ = self.fixture()
        d.A['low'][1, 0] = np.nan
        trades = [{'entry': '2025-01-02', 'exit': '2025-01-03'}]
        self.assertEqual(holding_missing(d, 0, trades), ['2025-01-03'])


if __name__ == '__main__':
    unittest.main()
