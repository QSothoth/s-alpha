import unittest

from studies.trader_replication.martin_continue_dm import paired_labels


class PairedOutcomeTest(unittest.TestCase):
    def test_independent_maturity_is_paired_per_metric(self):
        a, b = paired_labels({'quick': True, 'ret': None}, {'quick': False, 'ret': .2})
        self.assertEqual(a, {'quick': True, 'ret': None})
        self.assertEqual(b, {'quick': False, 'ret': None})
        a, b = paired_labels({'quick': None, 'ret': .4}, {'quick': True, 'ret': -.1})
        self.assertEqual(a, {'quick': None, 'ret': .4})
        self.assertEqual(b, {'quick': None, 'ret': -.1})


if __name__ == '__main__':
    unittest.main()
