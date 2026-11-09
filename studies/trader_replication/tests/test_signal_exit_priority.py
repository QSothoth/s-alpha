import unittest

import numpy as np

from studies.trader_replication.tests.test_day_trim_signal_add import UP, run


class SignalExitPriorityTests(unittest.TestCase):
    def test_known_exit_skips_close_add_and_avoids_round_trip_cost(self):
        exit_mask = np.zeros((len(UP), 1), dtype=bool)
        exit_mask[1] = True
        kwargs = dict(ema={'exit': exit_mask}, exit_signal='exit', add_r=1.,
                      buy_cost=.001, sell_cost=.001)
        _, _, (legacy,) = run(UP, **kwargs)
        _, _, (fixed,) = run(UP, exit_signal_cancel_add=True, **kwargs)
        self.assertEqual([e['action'] for e in legacy['executions']], ['entry', 'add', 'signal'])
        self.assertEqual([e['action'] for e in fixed['executions']], ['entry', 'signal'])
        self.assertEqual((fixed['exit'], fixed['why']), (legacy['exit'], legacy['why']))
        addition = legacy['executions'][1]
        self.assertAlmostEqual(fixed['pnl'] - legacy['pnl'], addition['price'] * addition['shares'] * .002)

    def test_both_add_kinds_skip_only_on_signal_exit(self):
        exit_mask = np.zeros((len(UP), 1), dtype=bool)
        add_mask = np.zeros((len(UP), 1), dtype=bool)
        exit_mask[1] = add_mask[1] = True
        params = dict(ema={'exit': exit_mask, 'buy': add_mask}, exit_signal='exit',
                      add_signal='buy', add_r=1., exit_signal_cancel_add=True)
        _, _, (t,) = run(UP, **params)
        self.assertEqual([e['action'] for e in t['executions']], ['entry', 'signal'])
        exit_mask[1] = False
        _, _, (t,) = run(UP, **params)
        self.assertEqual(sum(e['action'] == 'add' for e in t['executions']), 2)


if __name__ == '__main__':
    unittest.main()
