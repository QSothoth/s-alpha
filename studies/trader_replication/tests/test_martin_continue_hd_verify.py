import unittest

from studies.trader_replication.martin_continue_hd_verify import compare_plans


class PlanComparisonTest(unittest.TestCase):
    def test_compares_status_size_and_fraction_separately(self):
        def days(shares, fraction, execution):
            return [{'day': '2025-01-02', 'fraction': fraction, 'orders': [
                {'type': 'entry', 'kind': 'n1', 'code': 'US.A', 'status': 'submitted',
                 'shares': shares, 'execution': execution}]}]
        result = compare_plans(days(.1, .005, 'filled'), days(.2, .0025, 'filled'))
        self.assertEqual((result['status_changed'], result['shares_differ']), (0, 1))
        self.assertEqual(result['fraction_changed_days'], ['2025-01-02'])
        result = compare_plans(days(.1, .005, 'filled'), days(.1, .005, 'limit_expired'))
        self.assertEqual((result['status_changed'], result['shares_differ']), (1, 0))


if __name__ == '__main__':
    unittest.main()
