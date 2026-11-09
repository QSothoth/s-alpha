import unittest

from studies.trader_replication.martin_continue_bt import narrow


class NarrowStopTests(unittest.TestCase):
    def test_filter_retains_boundary_and_core_without_changing_stops(self):
        core = ((0,), 0, 1, 100., 90., 'core')
        exact = ((1,), 1, 1, 100., 97., 'list')
        wide = ((2,), 2, 1, 100., 96.99, 'list')
        near = ((3,), 3, 1, 100., 99., 'list')
        self.assertEqual(narrow([[core, exact, wide, near]]), [[core, exact, near]])


if __name__ == '__main__':
    unittest.main()
