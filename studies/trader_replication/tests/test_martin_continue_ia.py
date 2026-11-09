import unittest
from types import SimpleNamespace

import numpy as np

from studies.trader_replication.martin_continue_ia import collect_funnel
from studies.trader_replication.martin_strong_scan import hold_sim


class ExpandedWatchlistTest(unittest.TestCase):
    def test_wider_hysteresis_contains_original_without_future_rows(self):
        rng = np.random.default_rng(20)
        score = rng.normal(size=(20, 80)).astype(np.float32)
        score[5:8, 0] = np.nan
        small, wide = hold_sim(score, 12, 36), hold_sim(score, 20, 60)
        self.assertFalse(np.any(small & ~wide))
        changed = score.copy()
        changed[10:] *= -100
        np.testing.assert_array_equal(wide[:10], hold_sim(changed, 20, 60)[:10])

    def test_funnel_never_combines_stages_from_different_days(self):
        days = np.array(['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04'])
        data = SimpleNamespace(days=days, di={day: i for i, day in enumerate(days)},
                               A={'codes': np.array(['US.A'])})
        mask = np.ones((4, 1), dtype=bool)
        held = np.array([[False], [False], [True], [True]])
        core = ((0., 0.), 0, 1, 10., 9., 'n1')
        book = [[], [core], [], []]
        target = {'id': 'X', 'code': 'US.A', 'entry_date': '2024-01-03',
                  'window': ['2024-01-03', '2024-01-04']}
        result = collect_funnel(data, mask, held, book, [target])
        reached = result['rows'][0]['reached']
        self.assertEqual(reached, {'active': True, 'held': True, 'qualified': False,
                                   'selected': False, 'core': True})
        self.assertEqual(result['summary']['2024_2025']['first_gap']['qualified'], 1)


if __name__ == '__main__':
    unittest.main()
