"""Per-kind open-position caps (Flanders: base buys must not take every slot from the EPs that come later)."""
import unittest

import numpy as np

from studies.trader_replication import system as Y

DATES = np.array(['2025-01-28', '2025-01-29', '2025-01-30'])
RULES = dict(buy_cost=0, sell_cost=0, margin_rate=0, trail='', trims=(), risk=.01, max_position=10.0, max_gross=10.0)
FLAT = np.full((3, 3), 10.0)
PX = {'open': FLAT, 'high': FLAT + .1, 'low': FLAT - .1, 'close': FLAT, 'dates': DATES,
      'codes': np.array(['US.A', 'US.B', 'US.C'])}


def run(**kw):
    e = [[] for _ in DATES]
    e[0] += [(0, 0, 1, 10.0, 9.5, 'pb'), (1, 1, 1, 10.0, 9.5, 'pb')]
    e[1] += [(0, 2, 1, 10.0, 9.5, 'ep')]
    _, _, tr = Y.simulate(PX, {}, Y.Rules(**{**RULES, **kw}), e, DATES[0], DATES[-1])
    return sorted((t['code'], t['entry']) for t in tr)


class OpenByKindTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(len(run()), 3)

    def test_cap_on_one_kind_leaves_room_for_another(self):
        self.assertEqual(run(max_open_by_kind={'pb': 1}), [('US.A', '2025-01-28'), ('US.C', '2025-01-29')])

    def test_global_cap_still_applies(self):
        self.assertEqual(run(max_open=2), [('US.A', '2025-01-28'), ('US.B', '2025-01-28')])
        self.assertEqual(run(max_open=2, max_open_by_kind={'pb': 1}), [('US.A', '2025-01-28'), ('US.C', '2025-01-29')])


if __name__ == '__main__':
    unittest.main()
