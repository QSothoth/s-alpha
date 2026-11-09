import unittest

from studies.trader_replication.martin_continue_hg import event


class H3PathTest(unittest.TestCase):
    def test_h3_is_cumulative_and_core_is_independent(self):
        self.assertEqual(event(True, True, False, False, True),
                         {'active': True, 'held': True, 'qualified': False,
                          'selected': False, 'core': True})
        with self.assertRaisesRegex(AssertionError, 'not cumulative'):
            event(True, False, True, False, False)
        with self.assertRaisesRegex(AssertionError, 'not cumulative'):
            event(False, True, True, True, False)


if __name__ == '__main__':
    unittest.main()
