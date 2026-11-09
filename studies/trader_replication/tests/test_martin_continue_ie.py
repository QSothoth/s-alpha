from datetime import date, timedelta
from types import SimpleNamespace
import unittest

import numpy as np

from studies.trader_replication.martin_continue_ie import (
    CATEGORIES, FRAME_IDS, category, completed_week, coverage, entry_nights,
    group_percentiles, random_probability, ranks, reference_inputs, reference_snapshot, target_label,
)
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_strong_scan import HOLD, hold_sim


def sample():
    days = []
    day = date(2024, 1, 1)
    while len(days) < 80:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    rates = np.linspace(.0001, .02, 16)
    c = 10 * (1 + rates[None, :]) ** np.arange(80)[:, None]
    return SimpleNamespace(days=days, codes=[f'US.X{i:02d}' for i in range(16)], c=c,
        t=np.full(c.shape, 2e8), volume=np.full(c.shape, 2e7), raw_v5=np.full(c.shape, .05))


class NoFutureReads:
    def __init__(self, values, cutoff):
        self.values, self.cutoff = values, cutoff

    def __getitem__(self, key):
        if not isinstance(key, slice) or key.stop is None or key.stop > self.cutoff + 1:
            raise AssertionError('attempted to read beyond the evening')
        return self.values[key]


def event(day, **kwargs):
    return dict(date=day, active=False, held=False, qualified=False, selected=False, core=False, **kwargs)


class IETimelineTests(unittest.TestCase):
    def test_reference_frames_never_read_data_after_evening(self):
        data = sample()
        evening = 43
        expected = reference_snapshot(data, evening)
        guarded = SimpleNamespace(**vars(data))
        for key in ('c', 't', 'volume', 'raw_v5'):
            setattr(guarded, key, NoFutureReads(getattr(data, key), evening))
        actual = reference_snapshot(guarded, evening)
        for name in FRAME_IDS:
            np.testing.assert_array_equal(actual['frames'][name]['rank'], expected['frames'][name]['rank'])
        for key in ('c', 't', 'volume', 'raw_v5'):
            getattr(data, key)[evening + 1:] = 1e12
        changed = reference_snapshot(data, evening)
        for name in FRAME_IDS:
            np.testing.assert_array_equal(changed['frames'][name]['rank'], expected['frames'][name]['rank'])
            np.testing.assert_allclose(changed['frames'][name]['value'], expected['frames'][name]['value'])

    def test_truncated_price_inputs_and_column_rescaling_preserve_ranks(self):
        data = sample()
        evening = 43
        expected = reference_snapshot(data, evening)
        cut = SimpleNamespace(**vars(data))
        for key in ('c', 't', 'volume', 'raw_v5'):
            setattr(cut, key, getattr(data, key)[:evening + 1].copy())
        scale = np.linspace(.01, 10, 16)
        cut.c *= scale
        cut.volume /= scale
        actual = reference_snapshot(cut, evening)
        for name in FRAME_IDS:
            np.testing.assert_array_equal(actual['frames'][name]['rank'], expected['frames'][name]['rank'])

    def test_weekend_leader_is_frozen_during_week(self):
        data = sample()
        monday = next(i for i in range(30, 60) if date.fromisoformat(data.days[i]).weekday() == 0)
        a = reference_snapshot(data, monday)['frames']['leader_weekend']
        data.c[monday + 1, 0] *= 10
        data.volume[monday + 1, 0] *= 10
        b = reference_snapshot(data, monday + 1)['frames']['leader_weekend']
        np.testing.assert_array_equal(a['rank'], b['rank'])
        np.testing.assert_array_equal(a['value'], b['value'])
        self.assertEqual(data.days[completed_week(data.days, monday)[1]], data.days[monday - 1])

    def test_holiday_week_uses_known_calendar_without_next_week_prices(self):
        days = ['2024-03-25', '2024-03-26', '2024-03-27', '2024-03-28', '2024-04-01']
        self.assertEqual(completed_week(days, 3), (0, 3))
        self.assertEqual(completed_week(days, 2), (None, None))

    def test_2026_reference_computation_is_rejected(self):
        data = sample()
        data.days[43] = '2026-01-02'
        with self.assertRaisesRegex(ValueError, '2026'):
            reference_snapshot(data, 43)

    def test_raw_weekly_proxy_requires_five_complete_market_days(self):
        data = sample()
        data.A = {'codes': data.codes}
        data.di = {day: i for i, day in enumerate(data.days)}
        dataset = SimpleNamespace(actions=lambda: {}, rows=lambda: iter([
            (data.codes[0], day, [10., 11., 10., 10., 1e6, 1e7])
            for i, day in enumerate(data.days) if i != 40]))
        volume, volatility = reference_inputs(dataset, data)
        self.assertTrue(np.isnan(volatility[:4, 0]).all())
        self.assertAlmostEqual(float(volatility[39, 0]), .1)
        self.assertTrue(np.isnan(volatility[40:45, 0]).all())
        self.assertAlmostEqual(float(volatility[45, 0]), .1)
        self.assertTrue(np.isnan(volume[40, 0]))

    def test_scope_exclusion_is_not_a_bad_finite_rank(self):
        data = sample()
        data.t[:, 0] = 1e6
        data.raw_v5[:, 1] = .01
        result = reference_snapshot(data, 43)['frames']
        self.assertEqual(result['potent_day']['rank'][0], 0)
        self.assertEqual(result['potent_day']['rank'][1], 0)
        self.assertEqual(result['premier_liquidity']['rank'][0], 0)
        self.assertGreater(result['premier_liquidity']['rank'][1], 0)

    def test_coverage_uses_four_prior_nights_and_separates_prior_evening(self):
        self.assertEqual(entry_nights(10), [6, 7, 8, 9])
        self.assertEqual(entry_nights(2), [0, 1])
        events = [dict(rank=rank, width=100) for rank in (5, None, 40, 20)]
        row = dict(target=dict(tier='primary', censored=False, provisional=False), systems={'frame': events})
        result = coverage([row], 'frame')
        self.assertEqual(result['top']['5']['hits'], 1)
        self.assertEqual(result['top']['3']['hits'], 0)
        self.assertEqual(result['top']['5']['prior_evening_hits'], 0)
        self.assertAlmostEqual(result['top']['5']['random_expected_hits'], 1 - .95 ** 3)
        self.assertEqual(random_probability([dict(rank=None, width=100)], 10), 0)

    def test_primary_label_excludes_entry_high_and_marks_right_censoring(self):
        close, high = np.full(100, 10.), np.full(100, 11.)
        high[10] = 1000
        high[71] = 1000
        self.assertEqual(target_label(close, high, 10)['tier'], 'secondary')
        high[70] = 13
        result = target_label(close, high, 10)
        self.assertEqual(result['tier'], 'primary')
        self.assertTrue(result['complete'])
        high[91] = 14
        self.assertTrue(target_label(close, high, 90)['censored'])
        high[91:] = 11
        self.assertTrue(target_label(close, high, 90)['provisional'])

    def test_all_seven_categories_and_core_rescue(self):
        base = [event(str(i)) for i in range(1, 5)]
        self.assertEqual(category(base, base), CATEGORIES[0])
        self.assertEqual(category([dict(base[0], active=True)], base), CATEGORIES[1])
        self.assertEqual(category([event('5') | {'held': True}], base), CATEGORIES[2])
        self.assertEqual(category([event('0') | {'held': True}], base), CATEGORIES[3])
        for key, expected in (('held', 4), ('qualified', 5), ('selected', 6), ('core', 6)):
            nights = [dict(base[0], **{key: True})] + base[1:]
            self.assertEqual(category(base, nights), CATEGORIES[expected])

    def test_h4_group_decomposition_and_holding_ignore_future_fields(self):
        rng = np.random.default_rng(42)
        mask = np.ones((15, 80), bool)
        fields = {key: rng.normal(size=mask.shape).astype(np.float32) for group in HOLD['H4'] for key in group}
        score = daily_name_score(fields, mask, HOLD['H4'])
        holding = hold_sim(score, 12, 36)
        groups = group_percentiles(fields, mask, 8)
        np.testing.assert_allclose((groups - .5).sum(0), score[8], atol=1e-6)
        for field in fields.values():
            field[8:] *= -100
        changed = daily_name_score(fields, mask, HOLD['H4'])
        np.testing.assert_array_equal(score[:9], changed[:9])
        np.testing.assert_array_equal(holding[:9], hold_sim(changed, 12, 36)[:9])

    def test_h4_ties_match_original_full_sort_and_reference_ties_use_code(self):
        value = np.full(100, np.nan)
        mask = np.arange(100) % 3 == 0
        value[mask] = 1
        _, order = ranks(value, mask)
        expected = np.argsort(-np.nan_to_num(value, nan=-1e9))
        np.testing.assert_array_equal(order, expected[mask[expected]])
        rank, _ = ranks(np.ones(3), np.ones(3, bool), ['US.C', 'US.A', 'US.B'])
        np.testing.assert_array_equal(rank, [3, 1, 2])


if __name__ == '__main__':
    unittest.main()
