import unittest

import numpy as np

from studies.trader_replication.martin_continue_hu import turnover_union


class TurnoverUnionTest(unittest.TestCase):
    def test_union_deduplicates_and_uses_signal_prior_turnover(self):
        def order(code, kind, priority):
            return {'day': 'd2', 'signal_day': 'd1', 'code': code, 'kind': kind,
                    'priority': [2., 1., priority], 'close': 10., 'stop': 9.}
        core = order('J', 'n1', 0.)
        h4 = [core] + [order(c, 'list', i) for i, c in enumerate('ABCDEF')]
        h3 = [core] + [order(c, 'list', i) for i, c in enumerate('BCDEFG')]
        values = np.zeros((3, 10))
        values[0, :7] = [1, 2, 3, 4, 5, np.nan, 9]
        values[1, :7] = [99, 0, 0, 0, 0, 0, 0]
        codes = {c: i for i, c in enumerate('ABCDEFGHIJ')}
        out = turnover_union(h3, h4, {'d0': 0, 'd1': 1, 'd2': 2}, codes, values)
        self.assertEqual(out[0], core)
        self.assertEqual([x['code'] for x in out[1:]], list('GEDCBA'))
        self.assertEqual(h4[1]['priority'], [2., 1., 0])

    def test_duplicate_with_different_execution_values_rejected(self):
        row = {'day': 'd2', 'signal_day': 'd1', 'code': 'A', 'kind': 'list',
               'priority': [2., 1., 0.], 'close': 10., 'stop': 9.}
        with self.assertRaises(AssertionError):
            turnover_union([dict(row, stop=8.)], [row], {'d1': 1}, {'A': 0}, np.zeros((2, 1)))


if __name__ == '__main__':
    unittest.main()
