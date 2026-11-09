import unittest
from studies.trader_replication.martin_continue_dx import spaced


class SpacingTests(unittest.TestCase):
    def test_one_clock_per_symbol_independent_of_candidate_type(self):
        last = {}
        self.assertEqual(spaced([[3, 'h3'], [4, 'other']], 10, last), [[3, 'h3'], [4, 'other']])
        self.assertEqual(spaced([[3, 'other'], [4, 'h3']], 30, last), [])
        self.assertEqual(spaced([[3, 'other']], 31, last), [[3, 'other']])
        self.assertEqual(spaced([[3, 'h3']], 32, last), [])


if __name__ == '__main__':
    unittest.main()
