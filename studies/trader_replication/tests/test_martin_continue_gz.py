import unittest
from types import SimpleNamespace

import numpy as np

from studies.trader_replication.system import Rules, simulate
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_gz import feedback_trace


class PriorCloseFeedbackTest(unittest.TestCase):
    def run_account(self, *, prior, late=False, opened=False):
        dates = np.array(['2025-01-02', '2025-01-03'])
        op = np.array([[10., 10.], [8., 10.]])
        px = {'dates': dates, 'codes': np.array(['US.EXIT', 'US.NEW']), 'open': op,
              'high': op.copy(), 'low': op.copy(), 'close': op.copy()}
        a = (0, 0, 1, 10., 9., 'open')
        b = (0, 1, 1, 10., 9., 'close' if late else 'open')
        rules = Rules(risk=.01, risk_low=.0025, feedback=1, feedback_opened=opened,
                      feedback_prior_close=prior, trail='', trims=(), intraday_kinds=('open',),
                      max_position=1., max_gross=2., buy_cost=0., sell_cost=0., margin_rate=0.)
        return simulate(px, {}, rules, [[a], [b]], dates[0], dates[-1], audit=True)[2]

    def test_gap_exit_cannot_change_the_same_open_risk_tier(self):
        old = self.run_account(prior=False)
        fixed = self.run_account(prior=True)
        self.assertEqual((old[0]['exit'], old[0]['why']), ('2025-01-03', 'gap_stop'))
        self.assertAlmostEqual(fixed[1]['executions'][0]['shares'], 4 * old[1]['executions'][0]['shares'])

    def test_close_entry_can_use_the_gap_exit(self):
        old = self.run_account(prior=False, late=True)
        fixed = self.run_account(prior=True, late=True)
        self.assertAlmostEqual(fixed[1]['executions'][0]['shares'], old[1]['executions'][0]['shares'])

    def test_trace_separates_same_open_exit_from_prior_close(self):
        days = np.array(['2025-01-02', '2025-01-03'])
        op = np.array([[10., 10.], [8., 10.]])
        codes = np.array(['US.EXIT', 'US.NEW'])
        px = {'dates': days, 'codes': codes, 'open': op, 'high': op, 'low': op, 'close': op}
        rules = Rules(risk=.01, risk_low=.0025, feedback=1, trail='', trims=(),
                      intraday_kinds=('open',), max_position=1., max_gross=2.,
                      buy_cost=0., sell_cost=0., margin_rate=0.)
        book = [[(0, 0, 1, 10., 9., 'open')], [(0, 1, 1, 10., 9., 'open')]]
        trades = simulate(px, {}, rules, book, days[0], days[-1], audit=True)[2]
        base = SimpleNamespace(px=lambda _: px, ema_inputs=lambda *args: {})
        d = SimpleNamespace(A={'codes': codes}, base=base, pool=None, days=days)
        trace, _ = feedback_trace(d, book, rules, digest(trades))
        self.assertEqual(trace['years']['2025']['risk_tier_differs'], 1)
        self.assertEqual(trace['years']['2025']['same_day_in_feedback'], 1)
        self.assertEqual(trace['entries'][1]['current_tier'], 'low')
        self.assertEqual(trace['entries'][1]['prior_tier'], 'normal')

    def test_opened_feedback_remains_its_own_prior_close_rule(self):
        old = self.run_account(prior=False, opened=True)
        fixed = self.run_account(prior=True, opened=True)
        self.assertEqual(old, fixed)


if __name__ == '__main__':
    unittest.main()
