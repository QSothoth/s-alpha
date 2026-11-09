import unittest

from studies.trader_replication.martin_continue_hc_marks import holding_requests


class PriorMarkTest(unittest.TestCase):
    def test_only_positions_held_before_open_need_prior_session_marks(self):
        days = ['2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07']
        account = {'plans': [{'day': d} for d in days],
                   'trades': [{'code': 'US.A', 'entry': days[0], 'exit': days[2]},
                              {'code': 'US.B', 'entry': days[1], 'exit': days[1]}]}
        result = holding_requests({'cash': account})
        self.assertEqual(dict(result), {('US.A', days[0]): {('cash', days[1])},
                                        ('US.A', days[1]): {('cash', days[2])}})


if __name__ == '__main__':
    unittest.main()
