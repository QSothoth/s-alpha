"""Hand-calculated OR2 costs, zero sessions and date-cluster inference."""
from datetime import date, timedelta
import json
import unittest

from studies.us_opening_range.context_stats import summarize_days


def profitable_days(count=60, per_day=2, gross=0.004):
    days = {}
    for index in range(count):
        start = date(2020, 1, 1) if index < 30 else date(2023, 1, 1)
        day = (start + timedelta(days=index % 30)).isoformat()
        days[day] = {'n_sessions': per_day, 'returns': [gross] * per_day}
    return days


class ContextStatsTests(unittest.TestCase):
    def test_costs_count_zero_trades_and_distinguish_three_weightings(self):
        result = summarize_days({'2020-01-02': {'n_sessions': 4, 'returns': [.004, -.001, .001]},
                                 '2023-01-02': {'n_sessions': 2, 'returns': [.003]}})
        self.assertEqual((result['n_sessions'], result['n_dates'], result['trades']), (6, 2, 4))
        self.assertEqual((result['wins'], result['losses'], result['zero_net_trades']), (2, 1, 1))
        self.assertAlmostEqual(result['coverage'], 4 / 6)
        self.assertEqual(result['win_rate'], .5)
        self.assertAlmostEqual(result['gross_mean_bp'], 17.5)
        self.assertAlmostEqual(result['net_mean_bp'], 7.5)
        self.assertAlmostEqual(result['stress_mean_bp'], -2.5)
        self.assertAlmostEqual(result['profit_factor'], 2.5)
        self.assertAlmostEqual(result['payoff_ratio'], 1.25)
        self.assertAlmostEqual(result['all_sessions_mean_bp'], 5)
        self.assertAlmostEqual(result['day_equal_mean_bp'], 6.25)
        self.assertAlmostEqual(result['halves']['before_2022_06_01']['net_mean_bp'], 10 / 3)
        self.assertAlmostEqual(result['halves']['from_2022_06_01']['net_mean_bp'], 20)
        self.assertFalse(result['selected_eligible'])

    def test_no_trade_dates_remain_zero_in_date_mean_and_bootstrap(self):
        result = summarize_days({'2020-01-02': {'n_sessions': 1, 'returns': [.011]},
                                 '2023-01-02': {'n_sessions': 1, 'returns': []}})
        self.assertEqual(result['trading_days'], 1)
        self.assertAlmostEqual(result['net_mean_lower_95_bp'], 100)
        self.assertAlmostEqual(result['day_equal_mean_bp'], 50)
        self.assertEqual(result['day_equal_mean_lower_95_bp'], 0)
        self.assertGreater(result['bootstrap']['undefined_trade_draws'], 0)
        self.assertEqual(result['bootstrap']['draws'], 2000)
        self.assertFalse(result['selected_eligible'])

    def test_empty_or_all_zero_exposure_has_no_spurious_success(self):
        empty = summarize_days({})
        self.assertEqual(empty['trades'], 0)
        self.assertIsNone(empty['net_mean_lower_95_bp'])
        self.assertFalse(empty['selected_eligible'])
        result = summarize_days({'2020-01-02': {'n_sessions': 14, 'returns': []}})
        self.assertEqual(result['all_sessions_mean_bp'], 0)
        self.assertEqual(result['day_equal_mean_lower_95_bp'], 0)
        self.assertIsNone(result['net_mean_lower_95_bp'])
        self.assertEqual(result['bootstrap']['undefined_trade_draws'], 2000)
        self.assertFalse(result['selected_eligible'])
        flat = summarize_days({'2020-01-02': {'n_sessions': 2, 'returns': [.001, .001]}})
        self.assertEqual((flat['trades'], flat['wins'], flat['losses']), (2, 0, 0))
        self.assertEqual(flat['net_mean_lower_95_bp'], 0)
        self.assertFalse(flat['gates']['profit_factor_at_least_1_2'])
        json.dumps([empty, result, flat], allow_nan=False)

    def test_date_bootstrap_is_deterministic_and_does_not_make_duplicates_independent(self):
        days = profitable_days(per_day=1)
        for index, value in enumerate(days.values()):
            value['returns'] = [.003 if index < 40 else -.001]
        result = summarize_days(days)
        reverse_order = dict(reversed(list(days.items())))
        self.assertEqual(result, summarize_days(reverse_order))
        repeated = {day: {'n_sessions': 14, 'returns': value['returns'] * 14}
                    for day, value in days.items()}
        replicated = summarize_days(repeated)
        self.assertAlmostEqual(result['net_mean_lower_95_bp'], replicated['net_mean_lower_95_bp'])
        self.assertAlmostEqual(result['day_equal_mean_lower_95_bp'], replicated['day_equal_mean_lower_95_bp'])

    def test_profitable_no_loss_sample_can_pass_without_serializing_infinity(self):
        result = summarize_days(profitable_days())
        self.assertEqual((result['trading_days'], result['trades']), (60, 120))
        self.assertIsNone(result['profit_factor'])
        self.assertIsNone(result['payoff_ratio'])
        self.assertAlmostEqual(result['net_mean_lower_95_bp'], 30)
        self.assertAlmostEqual(result['stress_mean_bp'], 20)
        self.assertTrue(result['selected_eligible'])
        json.dumps(result, allow_nan=False)

    def test_each_sample_half_and_stress_requirement_is_binding(self):
        too_few_dates = summarize_days(profitable_days(count=59))
        self.assertFalse(too_few_dates['gates']['at_least_60_trading_days'])
        self.assertTrue(too_few_dates['gates']['at_least_100_trades'])
        too_few_trades = summarize_days(profitable_days(per_day=1))
        self.assertFalse(too_few_trades['gates']['at_least_100_trades'])
        stress_failure = summarize_days(profitable_days(gross=.0015))
        self.assertTrue(stress_failure['gates']['positive_net_mean'])
        self.assertFalse(stress_failure['gates']['positive_stress_mean'])
        self.assertFalse(stress_failure['selected_eligible'])
        half_failure = profitable_days()
        for day, value in half_failure.items():
            if day < '2022-06-01':
                value['returns'] = [.001, .001]
        result = summarize_days(half_failure)
        self.assertFalse(result['gates']['positive_early_half'])
        self.assertTrue(result['gates']['positive_late_half'])
        self.assertFalse(result['selected_eligible'])

    def test_profit_factor_and_bootstrap_lower_are_independent_gates(self):
        low_pf = profitable_days()
        for value in low_pf.values():
            value['returns'] = [.111, -.099]
        result = summarize_days(low_pf)
        self.assertAlmostEqual(result['profit_factor'], 1.1)
        self.assertFalse(result['gates']['profit_factor_at_least_1_2'])
        self.assertTrue(all(value for key, value in result['gates'].items()
                            if key != 'profit_factor_at_least_1_2'))
        self.assertFalse(result['selected_eligible'])
        uncertain = profitable_days()
        for index, value in enumerate(uncertain.values()):
            value['returns'] = [.111 if index % 30 < 17 else -.099] * 2
        result = summarize_days(uncertain)
        self.assertLessEqual(result['net_mean_lower_95_bp'], 0)
        self.assertFalse(result['gates']['positive_trade_mean_lower_95'])
        self.assertTrue(all(value for key, value in result['gates'].items()
                            if key != 'positive_trade_mean_lower_95'))
        self.assertFalse(result['selected_eligible'])

    def test_half_split_date_is_in_late_half_and_100_trades_is_inclusive(self):
        days = profitable_days()
        for value in list(days.values())[:20]:
            value['returns'] = value['returns'][:1]
        self.assertTrue(summarize_days(days)['selected_eligible'])
        result = summarize_days({'2022-05-31': {'n_sessions': 1, 'returns': [.002]},
                                 '2022-06-01': {'n_sessions': 1, 'returns': [.004]}})
        self.assertAlmostEqual(result['halves']['before_2022_06_01']['net_mean_bp'], 10)
        self.assertAlmostEqual(result['halves']['from_2022_06_01']['net_mean_bp'], 30)

    def test_invalid_session_count_or_nonfinite_trade_is_rejected(self):
        invalid = [{'n_sessions': 0, 'returns': []}, {'n_sessions': True, 'returns': []},
                   {'n_sessions': 1, 'returns': [0, 0]}, {'n_sessions': 1, 'returns': [float('nan')]},
                   {'n_sessions': 1, 'returns': [float('inf')]}, {'n_sessions': 1, 'returns': [True]}]
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                summarize_days({'2020-01-02': item})
        with self.assertRaises(ValueError):
            summarize_days({'not-a-date': {'n_sessions': 1, 'returns': []}})


if __name__ == '__main__':
    unittest.main()
