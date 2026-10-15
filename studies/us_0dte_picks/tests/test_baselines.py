"""R29 must distinguish actual sales from expiry and observed value from theta."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from studies.us_0dte_picks.baselines import details, residual_values


class BaselineTests(unittest.TestCase):
    def test_residual_is_symmetric_and_not_clamped(self):
        opening = datetime(2026, 10, 14, 13, 30, tzinfo=timezone.utc)
        trade = dict(entry=dict(fill_minute=1, bar_close=3), exit=dict(fill_minute=2, bar_close=1))
        for direction, prices in (('LONG', (102, 101)), ('SHORT', (98, 99))):
            data = SimpleNamespace(case=SimpleNamespace(direction=direction, strike=100),
                session=SimpleNamespace(opens=opening, closes=opening + timedelta(minutes=390)), underlying=[
                    SimpleNamespace(close_time=opening + timedelta(minutes=i), close=p)
                    for i, p in enumerate(prices, 1)])
            self.assertEqual(residual_values(data, trade), dict(entry=1, exit=0))
            bad = dict(trade, entry=dict(fill_minute=1, bar_close=.5))
            self.assertEqual(residual_values(data, bad)['entry'], -1.5)

    def test_expiry_is_not_a_completed_sale_and_no_entry_stays_zero(self):
        entry = dict(minute=60, fill_minute=61, reason='deadline_entry')
        exit_ = dict(fill_minute=376, reason='scheduled_flatten')
        base = dict(scenario='trend_with', entry=entry, exit=exit_, outcome='COMPLETED',
                    net_return=.2, net_pnl=20, best_net_return=.3, hold_minutes=315,
                    failure=None, residual_value={})
        expired = dict(base, exit=dict(exit_, settled_at_expiry=True), outcome='EXIT_NOT_FILLED',
                       net_return=-1, net_pnl=-100)
        unentered = dict(base, entry=None, exit=None, outcome='NO_ENTRY_SIGNAL',
                         net_return=None, net_pnl=None, hold_minutes=None, failure='NO_ENTRY_SIGNAL')
        result = details([base, expired, unentered])
        self.assertEqual((result['cases'], result['entered'], result['sold'],
                          result['completed'], result['expired_settlement']), (3, 2, 1, 1, 1))
        self.assertAlmostEqual(result['raw']['expectancy'], -.8 / 3)
        self.assertEqual(details([])['cases'], 0)


if __name__ == '__main__':
    unittest.main()
