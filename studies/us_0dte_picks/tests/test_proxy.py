import unittest
from datetime import datetime, timedelta

from custody.marketdata import Bar
from custody.models import ET, Session
from studies.us_0dte_picks.proxy import atm_strike, bs_price, option_bars
from studies.us_0dte_picks.sv2_calibrate import spearman


class ProxyTests(unittest.TestCase):
    def test_black_scholes_parity_and_expiry(self):
        call, put = bs_price(100, 95, 0.0004, 'CALL'), bs_price(100, 95, 0.0004, 'PUT')
        self.assertAlmostEqual(call - put, 5.0, places=9)
        self.assertEqual(bs_price(100, 95, 0, 'CALL'), 5.0)
        self.assertEqual(bs_price(100, 95, 0, 'PUT'), 0.0)
        self.assertGreater(bs_price(100, 100, 0.0004, 'CALL'), bs_price(100, 100, 0.0001, 'CALL'))

    def test_bars_are_valid_decay_and_widen(self):
        opens = datetime(2026, 9, 21, 9, 30, tzinfo=ET)
        session = Session('2026-09-21', opens, opens.replace(hour=16, minute=0))
        under = [Bar('US.X', opens + timedelta(minutes=m), 100, 100.2, 99.8, 100, 1000) for m in range(1, 391)]
        bars = option_bars(under, session, 100.0, 'CALL', 0.30)
        wide = option_bars(under, session, 100.0, 'CALL', 0.30, w=0.2)
        self.assertEqual(len(bars), 390)
        self.assertGreater(bars[0].close, bars[300].close)  # flat underlying: time value decays
        self.assertEqual(bars[-1].close, 0.01)  # at the money at the close is worthless
        self.assertGreater(wide[100].high - wide[100].low, bars[100].high - bars[100].low)

    def test_strike_grid_and_rank_correlation(self):
        self.assertEqual(atm_strike('US.AAPL', 336.04), 335.0)
        self.assertEqual(atm_strike('US.INTC', 101.365), 101.5)
        self.assertAlmostEqual(spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)


if __name__ == '__main__':
    unittest.main()
