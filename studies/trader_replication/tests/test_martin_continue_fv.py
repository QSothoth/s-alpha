import unittest
from types import SimpleNamespace
import numpy as np
from studies.trader_replication.martin_continue_fv import wide_book


class WideStopTest(unittest.TestCase):
    def test_core_stop_and_precision_paths_leave_other_orders_alone(self):
        d = SimpleNamespace(days=['2024-01-02'], A={'low': np.array([[80., 88., 70.]], dtype=np.float32)})
        core = ((1,), 0, 1, 100., 90., 'n1', 90.)
        list_order = ((2,), 1, 1, 100., 90., 'list', 90.)
        other_core = ((3,), 2, 1, 100., 90., 'n1', 90.)
        original = [[core, list_order, other_core]]
        hit, a = wide_book(original, d, True)
        nohit, b = wide_book(original, d, False)
        self.assertEqual(hit[0][0][4:7], (80., 'n1', 80.))
        self.assertEqual(nohit[0][0][4:7], (80., 'n1', None))
        self.assertEqual(hit[0][1], list_order)
        self.assertEqual(hit[0][2][4:7], (80., 'n1', 80.))
        self.assertEqual(a['2024:unknown'], 1)
        self.assertEqual(a['2024:stop_day0'] - b['2024:stop_day0'], 1)
        self.assertEqual(original[0][0], core)

    def test_nonpositive_stop_stops_research(self):
        d = SimpleNamespace(days=['2024-01-02'], A={'low': np.array([[20.]], dtype=np.float32)})
        with self.assertRaises(ValueError):
            wide_book([[((1,), 0, 1, 100., 40., 'n1', None)]], d, True)


if __name__ == '__main__':
    unittest.main()
