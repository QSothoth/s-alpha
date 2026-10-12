import random
import csv
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from studies.us_0dte_picks.sv2 import (account, event_test, g13_tasks, minute_days, outside_strike, selection_s1)
from studies.us_0dte_picks.fetch_sv2 import COLUMNS, write_csv


def unit(symbol, day, usd, **flags):
    return {'symbol': symbol, 'day': day, 'pool': True, 'gap_atr': flags.get('gap_atr', 0.0), 'hv_iv': 1.0,
            'earnings_reaction': flags.get('earn', False), 'k4b': flags.get('k4b', False),
            'new': {'LONG': {'ret': usd / 100, 'fill_minute': 30, 'minute': 29}, 'SHORT': {'ret': None, 'fill_minute': None, 'minute': None}},
            'old': None}


class Sv2Tests(unittest.TestCase):
    def test_minute_reader_streams_days_and_rejects_missing_minute(self):
        with tempfile.TemporaryDirectory() as root:
            raw = Path(root)
            (raw / 'k1m').mkdir()
            def rows():
                for day, count in [('2026-07-01', 390), ('2026-07-02', 389), ('2026-07-03', 390)]:
                    start = datetime.fromisoformat(day + 'T09:30')
                    for i in range(1, count + 1):
                        yield dict(time_key=str(start + timedelta(minutes=i)),
                                   open=100, high=101, low=99, close=100, volume=10)
            write_csv(raw / 'k1m' / 'A.csv', rows(), COLUMNS)
            sessions = minute_days(raw, 'A', {'2026-07-01', '2026-07-02', '2026-07-03'})
            self.assertEqual(next(sessions)[0], '2026-07-01')
            self.assertEqual([(day, len(bars)) for day, bars in sessions], [('2026-07-03', 390)])

    def test_interrupted_download_is_not_a_complete_symbol(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'A.csv'
            def interrupted():
                yield {'time_key': '2026-07-01', 'open': 100}
                raise RuntimeError('disconnected')
            with self.assertRaisesRegex(RuntimeError, 'disconnected'):
                write_csv(target, interrupted(), COLUMNS)
            self.assertFalse(target.exists())
            self.assertTrue(target.with_suffix('.csv.tmp').exists())

    def test_account_view_drawdown_and_streak(self):
        a = account([('D1', 10, 100.0), ('D1', 20, -50.0), ('D2', 5, -30.0), ('D2', 9, 40.0)])
        self.assertEqual((a['trades'], a['total_usd'], a['max_drawdown_usd'], a['max_consecutive_losses']), (4, 60.0, 80.0, 2))
        self.assertEqual(a['worst_day_usd'], 10.0)
        self.assertAlmostEqual(a['payoff_ratio'], 70 / 40)

    def test_outside_strike_grid_follows_price(self):
        self.assertEqual((outside_strike(12.26), outside_strike(57.4), outside_strike(181.3)), (12.5, 57.0, 182.5))

    def test_g13_draws_follow_the_custody_order(self):
        cases = [{'minute': 30}, {'minute': None}, {'minute': 90}]
        entered, draws = g13_tasks(cases)
        rng = random.Random(20261002)
        self.assertEqual(len(entered), 2)
        self.assertEqual(draws[0], [rng.choice([30, 90]), rng.choice([30, 90])])

    def test_ranking_prefers_event_tier_then_score(self):
        units = []
        for d in ('D1', 'D2'):
            units += [unit('US.A', d, 50, earn=True), unit('US.B', d, 30, k4b=True),
                      unit('US.C', d, -40, gap_atr=5), unit('US.D', d, -40)]
        s1 = selection_s1(units)
        self.assertEqual((s1['top2_mean_usd'], s1['pool_mean_usd']), (40.0, 0.0))
        self.assertLessEqual(s1['p_vs_random_two'], 0.2)

    def test_event_permutation_is_stratified_by_date(self):
        units = [unit('US.A', 'D1', 100, earn=True), unit('US.B', 'D1', 0), unit('US.C', 'D2', 0, earn=True), unit('US.D', 'D2', 0)]
        r = event_test(units, lambda u: u['earnings_reaction'])
        self.assertEqual((r['event_mean_usd'], r['plain_mean_usd'], r['difference_usd']), (50.0, 0.0, 50.0))
        self.assertAlmostEqual(r['p_stratified_by_date'], 0.5, delta=0.03)  # only D1's assignment matters
        self.assertIsNone(event_test(units, lambda u: False))


if __name__ == '__main__':
    unittest.main()
