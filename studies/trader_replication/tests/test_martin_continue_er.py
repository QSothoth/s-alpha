import unittest
import numpy as np
from studies.trader_replication.martin_continue_er import ambiguous_orders


class FakeData:
    days = ['2024-01-02', '2024-01-03']
    A = {'codes': np.array(['US.A', 'US.B', 'US.C', 'US.D', 'US.E', 'US.F', 'US.G']),
         'open': np.array([[4.] * 7, [3.9600000381469727] + [4.] * 5 + [3.9600000381469727]])}


class PreselectedPrecisionTests(unittest.TestCase):
    def test_only_prior_top_six_are_checked_for_equal_float32_prices(self):
        prior = [((float(j),), j, 1, 4., 3.96, 'list') for j in range(7)]
        result = ambiguous_orders(FakeData(), [prior, []])
        self.assertEqual([row['code'] for row in result], ['US.A'])
        self.assertEqual(result[0]['signal_day'], '2024-01-02')


if __name__ == '__main__':
    unittest.main()
