import unittest

from studies.trader_replication.martin_continue_hk import randomize


class SamePoolRandomTest(unittest.TestCase):
    def test_core_and_candidate_fields_remain_fixed(self):
        core = ((0, -100), 0, 1, 10., 9., 'n1')
        a = ((2, 1, -.9), 1, 1, 10., 9., 'list')
        b = ((2, 1, -.8), 2, 1, 12., 11., 'list')
        book = [[core, a, b]]
        result = randomize(book, 1)
        self.assertEqual(result, randomize(book, 1))
        self.assertEqual(result[0][0], core)
        self.assertEqual([x[1:] for x in result[0][1:]], [a[1:], b[1:]])
        self.assertEqual(book, [[core, a, b]])
        self.assertNotEqual(result, randomize(book, 2))


if __name__ == '__main__':
    unittest.main()
