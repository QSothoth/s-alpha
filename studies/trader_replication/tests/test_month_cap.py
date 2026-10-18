"""Monthly loss cap (Christian Flanders: at most -5% a month, then 3% / 2% / 1% after losing months): which days
may still open trades."""
import unittest

import numpy as np

from studies.trader_replication import system as Y

DATES = np.array(['2025-01-28', '2025-01-29', '2025-01-30', '2025-01-31', '2025-02-03', '2025-02-04', '2025-02-05'])
RULES = dict(buy_cost=0, sell_cost=0, margin_rate=0, trail='', trims=(), risk=.01, max_position=10.0, max_gross=10.0)


def px(a_rows, b_rows):
    a, b = np.array(a_rows, float), np.array(b_rows, float)
    return {k: np.stack([a[:, i], b[:, i]], 1) for i, k in enumerate(('open', 'high', 'low', 'close'))} | \
        {'dates': DATES, 'codes': np.array(['US.A', 'US.B'])}


FLAT = [(10, 10.1, 9.9, 10)] * 7
# A: bought day 0 at 10 (stop 9.5), stopped on day 1 for -1R = -1% of equity
A = [(10, 10, 10, 10), (9.6, 9.6, 9.4, 9.45)] + [(9.5, 9.6, 9.4, 9.5)] * 5


def run(entries, **kw):
    p = px(A, FLAT)
    return Y.simulate(p, {}, Y.Rules(**{**RULES, **kw}), entries, DATES[0], DATES[-1], audit=True)


def entries(days):
    e = [[] for _ in DATES]
    e[0].append((0, 0, 1, 10.0, 9.5, 'a'))
    for d in days:
        e[d].append((0, 1, 1, 10.0, 9.5, 'b'))
    return e


class MonthCapTests(unittest.TestCase):
    def test_off_by_default(self):
        _, _, tr = run(entries([2]))
        self.assertEqual(sorted(t['entry'] for t in tr), ['2025-01-28', '2025-01-30'])

    def test_blocks_the_rest_of_the_month_then_resets(self):
        _, _, tr = run(entries([2]), month_loss_cap=.005)
        self.assertEqual(sorted(t['entry'] for t in tr), ['2025-01-28'])          # 01-30 blocked
        _, _, tr = run(entries([4]), month_loss_cap=.005)
        self.assertEqual(sorted(t['entry'] for t in tr), ['2025-01-28', '2025-02-03'])   # a new month

    def test_ladder_after_a_losing_month(self):
        # February cap .0001: B's first day already marks it down a little (close 10 -> 9.99), so 02-05 is blocked
        b = FLAT[:4] + [(10, 10.1, 9.9, 10), (10, 10.1, 9.9, 9.99), (10, 10.1, 9.9, 10)]
        p = px(A, b)
        e = entries([4])
        e[6].append((0, 0, 1, 9.5, 9.0, 'a2'))
        _, _, tr = Y.simulate(p, {}, Y.Rules(**RULES, month_loss_cap=.05, month_cap_ladder=(.0001,)), e,
                              DATES[0], DATES[-1])
        self.assertEqual(sorted(t['entry'] for t in tr), ['2025-01-28', '2025-02-03'])
        _, _, tr = Y.simulate(p, {}, Y.Rules(**RULES, month_loss_cap=.05), e, DATES[0], DATES[-1])
        self.assertEqual(sorted(t['entry'] for t in tr), ['2025-01-28', '2025-02-03', '2025-02-05'])


if __name__ == '__main__':
    unittest.main()
