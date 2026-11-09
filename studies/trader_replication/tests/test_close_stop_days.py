"""close_stop_days: for the first sessions after entry only a hard stop runs intraday; the initial stop needs a close."""
import unittest

import numpy as np

from studies.trader_replication import system
from studies.trader_replication.tests.test_system import NOCOST


def run(bars, **kw):
    """bars: (open, high, low, close) per session; entry at the first close 100 with stop 97 (R = 3)."""
    b = np.asarray([(100., 100., 100., 100.)] + bars, float)
    p = {k: b[:, i:i+1] for i, k in enumerate(('open', 'high', 'low', 'close'))}
    p.update(dates=np.array([f'2025-01-{i+2:02d}' for i in range(len(b))]), codes=np.array(['X']))
    rules = system.Rules(trail='', trims=(), **NOCOST, **kw)
    e = [[(0, 0, 1, 100., 97., 'k')]] + [[] for _ in bars]
    _, _, tr = system.simulate(p, {}, rules, e, p['dates'][0], p['dates'][-1], audit=True)
    return tr[0]


class CloseStopDaysTests(unittest.TestCase):
    def test_intraday_breach_survives_and_a_close_below_exits_at_that_close(self):
        t = run([(99, 100, 95, 98), (98, 99, 96, 96.5), (97, 99, 96, 98)], close_stop_days=2, hard_stop_mult=2)
        self.assertEqual((t['why'], t['exit']), ('close_stop', '2025-01-04'))
        self.assertAlmostEqual(t['executions'][-1]['price'], 96.5)

    def test_hard_stop_runs_intraday_and_at_the_open(self):
        t = run([(99, 100, 93, 98)], close_stop_days=2, hard_stop_mult=2)
        self.assertEqual(t['why'], 'stop')
        self.assertAlmostEqual(t['executions'][-1]['price'], 94.)
        t = run([(93.5, 95, 93, 94)], close_stop_days=2, hard_stop_mult=2)
        self.assertEqual(t['why'], 'gap_stop')
        self.assertAlmostEqual(t['executions'][-1]['price'], 93.5)

    def test_after_the_window_the_initial_stop_is_intraday_again(self):
        t = run([(99, 100, 98, 99), (99, 100, 98, 99), (99, 100, 96.9, 99)], close_stop_days=2, hard_stop_mult=2)
        self.assertEqual((t['why'], t['exit']), ('stop', '2025-01-05'))
        self.assertAlmostEqual(t['executions'][-1]['price'], 97.)

    def test_default_is_unchanged(self):
        t = run([(99, 100, 95, 98)])
        self.assertEqual((t['why'], t['exit']), ('stop', '2025-01-03'))
        self.assertAlmostEqual(t['executions'][-1]['price'], 97.)


class StopSlipTests(unittest.TestCase):
    def test_intraday_stop_slips_a_fraction_of_r_but_not_below_the_low_and_gaps_unchanged(self):
        t = run([(99, 100, 95, 98)], stop_slip_r=.1)
        self.assertAlmostEqual(t['executions'][-1]['price'], 97-.3)
        t = run([(99, 100, 96.9, 98)], stop_slip_r=.1)
        self.assertAlmostEqual(t['executions'][-1]['price'], 96.9)
        t = run([(96, 97, 95, 96)], stop_slip_r=.1)
        self.assertEqual((t['why'], t['executions'][-1]['price']), ('gap_stop', 96.))


class IntradayEmaStopTests(unittest.TestCase):
    def test_intraday_entry_with_ema_stop_only_keeps_its_initial_stop_on_the_fill_day(self):
        b = np.array([(100., 100., 100., 100.), (101., 103., 99.5, 102.), (102., 104., 101.5, 103.),
                      (103., 103.5, 99.8, 101.)])
        p = {k: b[:, i:i+1] for i, k in enumerate(('open', 'high', 'low', 'close'))}
        p.update(dates=np.array(['2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07']), codes=np.array(['X']))
        ema = {'e9': np.full((4, 1), 101.)}
        rules = system.Rules(trail='e9', trims=(), stop_ema_only=True, stop_ema_buffer=.01,
                             intraday_kinds=('k',), **NOCOST)
        e = [[], [(0, 0, 1, 101., 99., 'k', None)], [], []]
        _, _, tr = system.simulate(p, ema, rules, e, p['dates'][0], p['dates'][-1], audit=True)
        # fill day low 99.5 is under 101 * .99 but above the initial 99: held; armed at day 2's close, stopped day 3
        self.assertEqual((tr[0]['why'], tr[0]['exit']), ('stop', '2025-01-07'))
        self.assertAlmostEqual(tr[0]['executions'][-1]['price'], 101*.99)
        with self.assertRaises(ValueError):
            system.simulate(p, ema, system.Rules(**{**rules.__dict__, 'arm_trail_on_entry': True}), e,
                            p['dates'][0], p['dates'][-1])


if __name__ == '__main__':
    unittest.main()
