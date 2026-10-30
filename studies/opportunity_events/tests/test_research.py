import unittest
from datetime import datetime, timezone

from studies.opportunity_events.research import candidate, cap_group, premarket_window, summarize


class ResearchTests(unittest.TestCase):
    def test_premarket_excludes_closed_session_and_regular_open(self):
        at = datetime(2026, 10, 27, 13, 20, tzinfo=timezone.utc)
        self.assertTrue(premarket_window('PRE_MARKET_BEGIN', at))
        self.assertFalse(premarket_window('CLOSED', at))
        self.assertFalse(premarket_window('PRE_MARKET_BEGIN', at.replace(minute=30)))

    def test_premarket_uses_regular_last_not_prior_regular_close(self):
        at = datetime(2026, 10, 27, 13, 20, tzinfo=timezone.utc)
        r = dict(security='US.TEST', pre_market_price=110, close_price=100,
                 pre_market_change_ratio=10, pre_market_volume=1000, pre_market_turnover=110000)
        s = dict(update_time='2026-10-27 09:19:59', pre_price=110, last_price=100,
                 prev_close_price=90, pre_change_rate=10, bid_price=109.9, ask_price=110.1,
                 total_market_val=5e9, equity_valid=True)
        out = candidate(r, s, at)
        self.assertEqual(out['quality_flags'], [])
        self.assertEqual(out['cap_group'], '2b_to_10b')
        self.assertIsNone(out['direction'])
        s['ask_price'] = 115
        self.assertIn('spread_at_least_1pct', candidate(r, s, at)['quality_flags'])
        s['update_time'] = '2026-10-26 09:19:59'
        s['ask_price'] = 108
        out = candidate(r, s, at)
        self.assertIn('snapshot_wrong_date', out['quality_flags'])
        self.assertIn('missing_or_crossed_quote', out['quality_flags'])

    def test_unknown_and_boundary_market_caps(self):
        self.assertEqual(cap_group(float('nan')), 'unknown')
        self.assertEqual(cap_group(0), 'unknown')
        self.assertEqual(cap_group(2e9), '2b_to_10b')
        self.assertEqual(cap_group(10e9), '10b_plus')

    def test_summaries_count_events_and_dates_separately(self):
        events = [dict(symbol='A', date='2020-01-01', follow=.02, excess_spy=.01),
                  dict(symbol='B', date='2020-01-01', follow=-.01, excess_spy=-.02)]
        out = summarize(events, ['2020-01-01'], draws=10)
        self.assertEqual((out['n'], out['dates']), (2, 1))
        self.assertAlmostEqual(out['follow']['mean'], .005)
        self.assertAlmostEqual(out['fade']['mean'], -.005)
        self.assertAlmostEqual(out['follow']['after_20bp'], .003)
        self.assertEqual(out['follow']['mean_ci95'], [.005, .005])
        self.assertEqual(summarize([], []), dict(n=0, dates=0))


if __name__ == '__main__':
    unittest.main()
