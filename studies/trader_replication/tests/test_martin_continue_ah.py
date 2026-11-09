import unittest
from types import SimpleNamespace

import numpy as np

from studies.trader_replication.martin_continue_ah import delayed_list
from studies.trader_replication.martin_continue_aj import fixed_six


class DelayedList(unittest.TestCase):
    def test_same_day_cap_keeps_core_and_original_top_six(self):
        core = ((1.,), 9, 1, 10., 9., 'n1')
        entries = [((2., 1., float(i)), i, 1, 10., 9., 'list') for i in reversed(range(8))]
        row = fixed_six([[core, *entries]])[0]
        self.assertEqual(row[0], core)
        self.assertEqual([e[1] for e in row[1:]], list(range(6)))

    def test_preselects_six_without_replacement_and_marks_same_day_stop(self):
        op = np.full((2, 8), 10.)
        low = np.full_like(op, 9.5)
        op[1, 0] = 8.
        low[1, 1] = 8.5
        D = SimpleNamespace(days=['2024-01-02', '2024-01-03'], A={'open': op, 'low': low})
        entries = [((2., 1., float(i)), i, 1, 10., 9., 'list', None, None, None, .5) for i in range(8)]
        out, counts = delayed_list(D, [entries, []])
        self.assertEqual([e[1] for e in out[1]], [1, 2, 3, 4, 5])
        self.assertEqual(out[1][0][6], 9.)
        self.assertIsNone(out[1][1][6])
        self.assertEqual(counts['2024:preselected'], 6)
        self.assertEqual(counts['2024:open_below_stop'], 1)
        self.assertEqual(counts['2024:day_stop'], 1)
