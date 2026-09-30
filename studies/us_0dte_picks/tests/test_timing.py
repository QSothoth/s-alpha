"""Synthetic fixtures only; checks P1 definitions, never market data."""
from math import sqrt
import unittest

from studies.us_0dte_picks import timing


def session(open_=100.0, path=None, close=None):
    """78 bars on the 09:35..16:00 grid; `path` overrides closes of the first bars."""
    closes = list(path or []) + [open_] * (78 - len(path or []))
    if close is not None:
        closes[-1] = close
    bars, previous = [], open_
    for clock, price in zip(timing.GRID, closes):
        bars.append((clock, previous, max(previous, price) + .1, min(previous, price) - .1, price))
        previous = price
    return bars


class SummaryTests(unittest.TestCase):
    def test_incomplete_or_invalid_sessions_are_rejected(self):
        self.assertIsNone(timing.summarize(session()[:42]))
        broken = session()
        broken[5] = (broken[5][0], 100, 99, 101, 100)  # high below low
        self.assertIsNone(timing.summarize(broken))

    def test_decision_points_use_only_completed_bars(self):
        summary = timing.summarize(session(path=[101, 102, 103, 110], close=105))
        self.assertEqual(summary['at']['open']['price'], 100)
        self.assertEqual(summary['at']['09:45']['price'], 103)      # third bar closes 09:45
        self.assertAlmostEqual(summary['at']['09:45']['high'], 103.1)  # 110 is not seen yet
        self.assertAlmostEqual(summary['at']['09:45']['after_high'], 110.1)
        self.assertEqual(summary['close'], 105)


class NameDayTests(unittest.TestCase):
    def test_scores_and_targets_follow_the_registration(self):
        previous = timing.summarize(session(close=98))
        today = timing.summarize(session(open_=100, path=[101, 99, 102], close=104))
        record = timing.name_day('SPY', today, previous, (25.2, 30.0))
        sigma = .252 / sqrt(252)
        self.assertAlmostEqual(record['score']['P0'], 30 / 25.2)
        self.assertAlmostEqual(record['score']['O0'], (100 - 98) / 98 / sigma)   # gap only
        span = max(98, 102.1) - min(98, 98.9)
        self.assertAlmostEqual(record['score']['O15'], span / 98 / sigma)
        self.assertAlmostEqual(record['y']['open'], (104 / 100 - 1) / sigma)
        self.assertAlmostEqual(record['y']['09:45'], abs(104 / 102 - 1) / (sigma * sqrt(375 / 390)))

    def test_missing_inputs_drop_the_name_day(self):
        today = timing.summarize(session())
        self.assertIsNone(timing.name_day('SPY', today, None, (20, 20)))
        self.assertIsNone(timing.name_day('SPY', today, today, None))


class SelectionTests(unittest.TestCase):
    def test_iv_must_be_strictly_earlier_and_recent(self):
        series = (['2024-01-05', '2024-01-10'], [(20, 18), (22, 19)])
        self.assertEqual(timing.iv_before(series, '2024-01-10'), (20, 18))  # same-day IV is not known yet
        self.assertIsNone(timing.iv_before(series, '2024-01-05'))
        self.assertIsNone(timing.iv_before((['2024-01-02'], [(20, 18)]), '2024-01-12'))

    def test_picks_break_ties_by_symbol(self):
        records = [{'symbol': s, 'score': {'O0': v}} for s, v in (('B', 1), ('A', 1), ('C', 2), ('D', 0))]
        self.assertEqual([r['symbol'] for r in timing.picks(records, 'O0')], ['C', 'A', 'B'])

    def test_choose_prefers_the_earliest_near_best_passer(self):
        results = {name: {'gates': {'ok': False}, 'ci95': [0, 0]} for name in timing.CANDIDATES}
        results['O15'] = {'gates': {'ok': True}, 'ci95': [1.10, 0]}
        results['O60'] = {'gates': {'ok': True}, 'ci95': [1.115, 0]}
        self.assertEqual(timing.choose(results), 'O15')
        results['O60']['ci95'] = [1.13, 0]
        self.assertEqual(timing.choose(results), 'O60')
        self.assertIsNone(timing.choose({name: {'gates': {'ok': False}, 'ci95': [2, 0]}
                                         for name in timing.CANDIDATES}))

    def test_lift_is_pooled_mean_ratio(self):
        self.assertAlmostEqual(timing.lift([(2, 1), (1, 1)], 0, 1), 1.5)


if __name__ == '__main__':
    unittest.main()
