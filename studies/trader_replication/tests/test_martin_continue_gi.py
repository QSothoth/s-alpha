import unittest
from types import SimpleNamespace
import numpy as np
from studies.trader_replication.martin_continue_gi import assert_no_same_day_rebuy, fixed_book


class FixedOpenBookTest(unittest.TestCase):
    def fixture(self):
        days = ['2025-01-02', '2025-01-03']
        A = {'codes': np.array([f'US.{i}' for i in range(9)]),
             'open': np.full((2, 9), 100., dtype=np.float32),
             'low': np.full((2, 9), 99., dtype=np.float32)}
        d = SimpleNamespace(days=days, A=A)
        core = [[((1, 0), 0, 1, 100., 101., 'n1')], []]
        listed = [((2, i), i, 1, 100., 90., 'list', None, None, None, .5) for i in range(8, 0, -1)]
        return d, core, [listed, []]

    def test_prior_selection_is_fixed_when_the_next_day_low_changes(self):
        d, core, u1 = self.fixture()
        a, counts, _ = fixed_book(d, core, u1, True)
        self.assertEqual(len(a[1]), 7)
        self.assertEqual([e[1] for e in a[1] if e[5] == 'list'], [1, 2, 3, 4, 5, 6])
        self.assertEqual(counts['2025:n1:old_cancel_new_fillable'], 1)
        d.A['low'][1, 0] = 96.
        b, _, _ = fixed_book(d, core, u1, True)
        self.assertEqual([(e[0], e[1], e[3], e[4], e[5]) for e in a[1]],
                         [(e[0], e[1], e[3], e[4], e[5]) for e in b[1]])
        self.assertIsNone(a[1][0][6])
        self.assertEqual(b[1][0][6], 97.5)

    def test_precision_branches_and_missing_low(self):
        d, core, u1 = self.fixture()
        d.A['low'][1, 0] = 97.5
        a, _, _ = fixed_book(d, core, u1, True)
        b, _, _ = fixed_book(d, core, u1, False)
        self.assertEqual(a[1][0][6], 97.5)
        self.assertIsNone(b[1][0][6])
        d.A['low'][1, 0] = np.nan
        with self.assertRaises(ValueError):
            fixed_book(d, core, u1, True)

    def test_no_same_day_rebuy_is_a_real_trade_invariant(self):
        trades = [{'code': 'A', 'entry': '2025-01-01', 'exit': '2025-01-03'},
                  {'code': 'A', 'entry': '2025-01-03', 'exit': '2025-01-04'}]
        with self.assertRaises(AssertionError):
            assert_no_same_day_rebuy(trades)
        trades[1]['entry'] = '2025-01-06'
        trades[1]['exit'] = '2025-01-07'
        assert_no_same_day_rebuy(trades)


if __name__ == '__main__':
    unittest.main()
