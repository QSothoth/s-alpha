from dataclasses import replace
from datetime import date, timedelta
import unittest

from studies.trader_replication.ledger import Trade
from studies.trader_replication.martin_continue_ie_periods import (
    adjusted_bars, label_entry, merge_periods, spot_check, summarize,
)


def sample():
    days = [(date(2025, 1, 1) + timedelta(days=i)).isoformat() for i in range(200)]
    bars = {d: dict(open=11., high=12., low=10., close=11.) for d in days}
    trade = Trade('X1', 'AAA', 'long', days[80], days[80], days[80], 'exact',
                  'breakout', 'test', None, 'loss', -1., 'synthetic', 'test note')
    return days, bars, trade


class StrongPeriodsTests(unittest.TestCase):
    def test_exact_60_session_bounds_close_start_and_high_peak(self):
        days, bars, trade = sample()
        bars[days[19]]['close'] = 1.  # Day 61 before entry must be ignored.
        bars[days[20]]['close'] = 10.
        bars[days[20]]['high'] = 1000.  # Start day's high is outside the peak search.
        bars[days[140]]['high'] = 13.
        bars[days[141]]['high'] = 1000.  # Day 61 after entry must be ignored.
        row = label_entry(trade, days, bars)
        self.assertEqual((row['start'], row['end'], row['status']), (days[20], days[140], 'strong'))
        self.assertEqual(row['duration_sessions'], 120)
        self.assertAlmostEqual(row['raw_position']['time_fraction'], .5)
        self.assertAlmostEqual(row['raw_position']['rise_fraction_close_proxy'], 1 / 3)
        self.assertFalse(row['unfinished'])
        self.assertTrue(spot_check(row | {'period_id': 'test'}, days, bars)['minimum_close_verified'])

    def test_below_30_percent_is_retained_and_never_promoted_by_merge(self):
        days, bars, trade = sample()
        bars[days[20]]['close'] = 10.
        bars[days[100]]['high'] = 12.999
        row = label_entry(trade, days, bars)
        self.assertEqual(row['status'], 'no_obvious_strong_period')
        self.assertEqual(merge_periods([row], days, bars), [])
        self.assertEqual(row['outcome'], 'loss')

    def test_prior_peak_and_unbounded_position_are_exposed(self):
        days, bars, trade = sample()
        bars[days[20]]['close'] = 10.
        bars[days[30]]['high'] = 14.
        row = label_entry(trade, days, bars)
        self.assertEqual(row['end'], days[30])
        self.assertIn('peak_before_entry', row['flags'])
        self.assertEqual(row['raw_position']['time_fraction'], 6.)
        self.assertTrue(row['raw_position']['after_peak'])

    def test_ties_choose_earliest_day_and_entry_day_is_not_a_start(self):
        days, bars, trade = sample()
        for i in (20, 25, 80):
            bars[days[i]]['close'] = 10.
        for i in (100, 110):
            bars[days[i]]['high'] = 14.
        row = label_entry(trade, days, bars)
        self.assertEqual((row['start'], row['end']), (days[20], days[100]))
        bars[days[80]]['close'] = 1.
        self.assertEqual(label_entry(trade, days, bars)['start'], days[20])

    def test_cutoff_marks_unfinished_even_when_observed_peak_is_earlier(self):
        days, bars, trade = sample()
        bars[days[20]]['close'] = 10.
        bars[days[100]]['high'] = 14.
        row = label_entry(trade, days[:120], {d: bars[d] for d in days[:120]})
        self.assertTrue(row['unfinished'])
        self.assertEqual(row['available_future_sessions'], 39)
        self.assertEqual(row['end'], days[100])

    def test_chart_date_is_fixed_and_window_nominal_date_is_not_used(self):
        days, bars, trade = sample()
        chart = replace(trade, precision='chart', window_lo=days[79], window_hi=days[81])
        del bars[days[80]]
        row = label_entry(chart, days, bars)
        self.assertEqual(row['status'], 'missing_data')
        self.assertEqual(row['available_bars_in_ledger_window'], [days[79], days[81]])
        self.assertEqual(label_entry(replace(chart, precision='window'), days, bars)['status'], 'window_only')

    def test_missing_history_and_missing_peak_bar_are_explicit(self):
        days, bars, trade = sample()
        self.assertEqual(label_entry(trade, days, {days[80]: bars[days[80]]})['status'], 'insufficient_history')
        bars[days[20]]['close'] = 10.
        bars[days[100]]['high'] = 14.
        del bars[days[90]]
        row = label_entry(trade, days, bars)
        self.assertEqual(row['missing_peak_window_dates'], [days[90]])
        self.assertTrue(row['unfinished'])

    def test_transitive_overlap_merges_but_retains_every_trade_and_raw_interval(self):
        days, bars, trade = sample()
        rows = []
        for number, start, end, entry in ((1, 20, 50, 40), (2, 45, 90, 60), (3, 85, 110, 100), (4, 120, 140, 130)):
            bars[days[start]]['close'] = 10.
            bars[days[end]]['high'] = 14. + number
            rows.append(dict(id=f'X{number}', code='US.AAA', status='strong',
                             start=days[start], end=days[end], entry_date=days[entry], unfinished=number == 3))
        groups = merge_periods(rows, days, bars)
        self.assertEqual(len(groups), 2)
        self.assertEqual([r['id'] for r in groups[0]['entries']], ['X1', 'X2', 'X3'])
        self.assertEqual((groups[0]['start'], groups[0]['end']), (days[20], days[110]))
        self.assertEqual(groups[0]['entries'][0]['end'], days[50])
        self.assertTrue(groups[0]['unfinished'])

    def test_merged_endpoint_conflict_is_reported_without_shifting_end(self):
        days, bars, _ = sample()
        bars[days[40]]['high'] = 50.
        rows = [dict(id='A', code='US.AAA', status='strong', start=days[20], end=days[40],
                     entry_date=days[30], unfinished=False),
                dict(id='B', code='US.AAA', status='strong', start=days[35], end=days[100],
                     entry_date=days[60], unfinished=False)]
        group = merge_periods(rows, days, bars)[0]
        self.assertEqual(group['end'], days[100])
        self.assertEqual(group['highest_high_day'], days[40])
        self.assertIn('merged_end_is_not_highest_high', group['flags'])

    def test_shared_adjustment_prevents_split_from_creating_a_price_period(self):
        records = [('US.A', '2025-01-01', [100, 104, 98, 100]),
                   ('US.A', '2025-01-02', [50, 52, 49, 50])]
        bars, invalid = adjusted_bars(iter(records), [('2025-01-02', .5, 0)], cutoff='2025-01-02')
        self.assertFalse(invalid)
        self.assertEqual([bars[d]['close'] for d in bars], [50., 50.])
        with self.assertRaises(ValueError):
            adjusted_bars(iter(records + records), [])

    def test_summary_does_not_count_window_or_missing_rows_as_strong(self):
        days, bars, trade = sample()
        bars[days[20]]['close'] = 10.
        bars[days[100]]['high'] = 14.
        strong = label_entry(trade, days, bars)
        periods = merge_periods([strong], days, bars)
        rows = [strong, label_entry(replace(trade, id='W', precision='window'), days, bars),
                label_entry(replace(trade, id='M'), days, {})]
        result = summarize(rows, periods)['2024_2025']
        self.assertEqual(result['dated_longs'], 2)
        self.assertEqual(result['window_only'], 1)
        self.assertEqual(result['periods_by_first_entry'], 1)
        self.assertEqual(result['entry_time_fraction']['n'], 1)


if __name__ == '__main__':
    unittest.main()
