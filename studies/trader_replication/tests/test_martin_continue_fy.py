import unittest
from studies.trader_replication.martin_continue_fy import label_group, momentum


class PriorMomentumTest(unittest.TestCase):
    def test_corporate_actions_only_through_signal_day(self):
        days = [f'{i:03}' for i in range(130)]
        index = {day: i for i, day in enumerate(days)}
        rows = [(day, [100., 100., 100., 100. if i < 100 else 50., 1., 1.])
                for i, day in enumerate(days)]
        actions = [('100', .5, 0.), ('129', .5, 0.)]
        result = momentum(days, index, rows, actions, ['126', '128'])
        self.assertAlmostEqual(result['126'], 0.)
        self.assertAlmostEqual(result['128'], 0.)
        changed = momentum(days, index, rows[:129], actions[:1], ['126', '128'])
        self.assertEqual(result, changed)

    def test_missing_calendar_date_is_unknown_not_shifted(self):
        days = [f'{i:03}' for i in range(127)]
        index = {day: i for i, day in enumerate(days)}
        rows = [(day, [1., 1., 1., 1., 1., 1.]) for day in days if day != '000']
        self.assertIsNone(momentum(days, index, rows, [], ['126'])['126'])

    def test_ranking_uses_all_known_rows_before_outcome(self):
        rows = [{'code': 'B', 'momentum126': .5}, {'code': 'A', 'momentum126': .5},
                {'code': 'C', 'momentum126': .1}, {'code': 'D', 'momentum126': None}]
        self.assertEqual(label_group(rows), (3, 1))
        self.assertTrue(rows[1]['strength_high'])
        self.assertFalse(rows[0]['strength_high'])
        self.assertNotIn('strength_high', rows[3])


if __name__ == '__main__':
    unittest.main()
