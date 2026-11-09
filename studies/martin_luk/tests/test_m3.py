"""M3 observable execution timing, actual-stop retry and frozen selection gates."""
from dataclasses import replace
import unittest

import numpy as np

from studies.martin_luk import m3_research as M

Y = M.Y


class M3Tests(unittest.TestCase):
    def simulate(self, closes, lows=None, ema=None, **overrides):
        c = np.array(closes, float).reshape(-1, 1)
        days = np.array([f'2025-01-{d:02d}' for d in range(1, len(c)+1)])
        low = np.array(lows, float).reshape(-1, 1) if lows else c-.1
        px = dict(close=c, open=c, high=c+1, low=low, dates=days, codes=np.array(['A']))
        book = [[(0, 0, 1, 100., 90., 'close')]]+[[] for _ in range(len(c)-1)]
        rules = Y.Rules(risk=.01, max_position=.5, max_gross=2.8, trail='', trims=(),
                        buy_cost=0., sell_cost=0., margin_rate=0.)
        return Y.simulate(px, ema or {}, replace(rules, **overrides), book, days[0], days[-1], audit=True)[2]

    def test_confirmed_close_stop_starts_next_day(self):
        tr = self.simulate([100, 102, 101], [99, 95, 99], ema={'e21': np.full((3, 1), 98.)}, confirm_trail='e21')
        self.assertEqual(tr[0]['exit'], '2025-01-03')
        self.assertEqual(tr[0]['executions'][-1]['price'], 100.)
        self.assertEqual(tr[0]['confirmed_day'], '2025-01-02')

    def test_two_consecutive_closes_reset_after_reclaim(self):
        tr = self.simulate([100, 102, 99, 102, 99, 98], ema={'e21': np.full((6, 1), 100.)},
                           trail='e21', trail_confirm_days=2)
        self.assertEqual((tr[0]['exit'], tr[0]['why']), ('2025-01-06', 'trail'))

    def test_retry_requires_actual_clean_stop_and_is_not_recursive(self):
        ema = {'e9': np.full((5, 1), 95.), 'adr': np.full((5, 1), 10.)}
        tr = self.simulate([100, 96, 101, 95, 102], [99, 89, 100, 90, 101], ema=ema,
                           reentry_days=10, reentry_adr='adr', no_rebuy_day=True)
        self.assertEqual([t['kind'] for t in tr], ['close', 'reentry_close'])
        self.assertEqual(tr[1]['entry'], '2025-01-03')
        self.assertEqual(tr[1]['stop'], 99.99)
        # A high above 3R on an earlier surviving day disqualifies E10's clean-stop retry.
        no = self.simulate([100, 135, 95, 101], [99, 134, 89, 100],
            ema={'e9': np.full((4, 1), 95.), 'adr': np.full((4, 1), 10.)},
            reentry_days=10, reentry_adr='adr')
        self.assertEqual(len(no), 1)

    def test_retry_cannot_ignore_permission(self):
        ema = {'e9': np.full((4, 1), 95.), 'adr': np.full((4, 1), 10.), 'ok': np.zeros((4, 1), bool)}
        tr = self.simulate([100, 96, 101, 102], [99, 89, 100, 101], ema=ema,
                           reentry_days=10, reentry_adr='adr', reentry_filter='ok')
        self.assertEqual(len(tr), 1)

    def test_unfilled_original_does_not_create_retry_and_fresh_entry_has_priority(self):
        ema = {'e9': np.full((4, 1), 95.), 'adr': np.full((4, 1), 10.)}
        no = self.simulate([100, 96, 101, 102], [99, 89, 100, 101], ema=ema,
                           max_position=0., reentry_days=10, reentry_adr='adr')
        self.assertEqual(no, [])
        c = np.array([[100., 100.], [96., 100.], [101., 100.], [102., 100.]])
        low = c-.1
        low[1, 0] = 89.
        days = np.array(['2025-01-01', '2025-01-02', '2025-01-03', '2025-01-04'])
        px = dict(close=c, open=c, high=c+1, low=low, dates=days, codes=np.array(['A', 'B']))
        book = [[(0, 0, 1, 100., 90., 'close')], [], [(0, 1, 1, 100., 90., 'close')], []]
        rules = Y.Rules(risk=.01, trail='', trims=(), max_new_long=1, reentry_days=10, reentry_adr='adr')
        tr = Y.simulate(px, {'e9': np.full(c.shape, 95.), 'adr': np.full(c.shape, 10.)},
                        rules, book, days[0], days[-1], audit=True)[2]
        self.assertEqual([(t['code'], t['kind']) for t in tr], [('A', 'close'), ('B', 'close')])

    def test_defaults_leave_historical_policy_disabled(self):
        r = Y.Rules()
        self.assertEqual((r.confirm_trail, r.reentry_days, r.trail_confirm_days), ('', 0, 1))

    def test_capture_is_strict_gate_and_precedes_capital_in_sort(self):
        def row(capture=.2, capital=.2, h=10., dd=.5, count=0):
            return dict(H=h, cap_equity=capital, years={y: dict(target_count=count, cap_equity=capital,
                capture_total=capture, purity_gross=.3, maxdd=dd, targets=dict(checks=dict(trades=True, win=True)))
                for y in ('2024', '2025')})
        r = M.select(dict(A=row(.3, .21), B=row(.4, .2), C=row(.2)), row())
        self.assertEqual(r['chosen'], 'B')
        self.assertIn('worse_year_capture', r['failures']['C'])


if __name__ == '__main__':
    unittest.main()
