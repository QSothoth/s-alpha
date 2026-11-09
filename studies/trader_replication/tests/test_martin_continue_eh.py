import unittest
import numpy as np
from studies.trader_replication.martin_continue_eh import normalized


class FakeData:
    days = ['2024-01-02']
    c = np.array([[100., 50.]])
    A = {'codes': np.array(['US.A', 'US.B'])}


class NormalizedSignalTests(unittest.TestCase):
    def test_common_price_scale_preserves_decision_and_relative_stops(self):
        book = [[((2.,), 0, 1, 100., 95., 'list', None), ((1.,), 1, 1, 50., 45., 'lim', 45.)]]
        result = normalized(book, FakeData(), '2024-01-02')['2024-01-02']
        self.assertEqual([row['code'] for row in result], ['US.B', 'US.A'])
        self.assertEqual(result[0]['stop_over_fill'], .9)
        self.assertEqual(result[0]['dayexit_over_fill'], .9)
        self.assertEqual(result[1]['fill_over_close'], 1.)


if __name__ == '__main__':
    unittest.main()
