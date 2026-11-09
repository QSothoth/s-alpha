import unittest
from studies.trader_replication.martin_continue_ga import compression, label_narrow


class CompressionTest(unittest.TestCase):
    def test_previous_three_sessions_adjusted_without_future(self):
        days = [f'{i:03}' for i in range(5)]
        index = {d: i for i, d in enumerate(days)}
        rows = [('000', [100., 102., 98., 100., 1., 1.]),
                ('001', [50., 51., 49., 50., 1., 1.]),
                ('002', [50., 51., 49., 50., 1., 1.]),
                ('003', [500., 900., 100., 500., 1., 1.]),
                ('004', [20., 21., 19., 20., 1., 1.])]
        actions = [('001', .5, 0.), ('003', .1, 0.)]
        result = compression(days, index, rows, actions, ['003'])['003']
        self.assertAlmostEqual(result, .04)
        self.assertEqual(result, compression(days, index, rows[:3], actions[:1], ['003'])['003'])

    def test_missing_market_session_is_unknown(self):
        days = [f'{i:03}' for i in range(4)]
        index = {d: i for i, d in enumerate(days)}
        rows = [(d, [10., 11., 9., 10., 1., 1.]) for d in ('000', '002')]
        self.assertIsNone(compression(days, index, rows, [], ['003'])['003'])

    def test_narrow_ranks_before_outcomes_with_ties_by_code(self):
        rows = [{'code': 'B', 'compression3': .1}, {'code': 'A', 'compression3': .1},
                {'code': 'C', 'compression3': .2}, {'code': 'D', 'compression3': None}]
        self.assertEqual(label_narrow(rows), 3)
        self.assertTrue(rows[1]['narrow'])
        self.assertFalse(rows[0]['narrow'])
        self.assertNotIn('narrow', rows[3])


if __name__ == '__main__':
    unittest.main()
