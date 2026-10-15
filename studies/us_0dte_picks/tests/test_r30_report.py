"""Selection diagnostics use all rows and choose daily plans without returns."""
import unittest

from studies.us_0dte_picks.r30_report import daily_tracks, paired_intervals


class ReportTests(unittest.TestCase):
    def trade(self, symbol, direction, net_return):
        return dict(symbol=symbol, contract=symbol + direction, direction=direction, trade_date='2026-01-02',
                    scenario='trend_with', entry=None if net_return is None else {'price': 1, 'reason': 'test'}, exit=None,
                    outcome='NO_ENTRY_SIGNAL' if net_return is None else 'COMPLETED',
                    net_return=net_return, net_pnl=None if net_return is None else net_return * 100,
                    failure=None, best_net_return=None, hold_minutes=None)

    def test_daily_plan_does_not_choose_the_profitable_symbol(self):
        rows = [self.trade('US.ZZZ', 'LONG', 2), self.trade('US.AAA', 'LONG', -.2),
                self.trade('US.ZZZ', 'SHORT', 2), self.trade('US.AAA', 'SHORT', -.5)]
        tracks = daily_tracks(rows)
        self.assertEqual(tracks['CALL']['plans'][0]['symbol'], 'US.AAA')
        self.assertEqual(tracks['PUT']['plans'][0]['symbol'], 'US.AAA')
        self.assertEqual(tracks['CALL']['raw_mean_return'], -.2)
        self.assertEqual(tracks['PUT']['days'], 1)

    def test_identical_paired_paths_have_zero_interval(self):
        rows = []
        for day in ('2026-01-02', '2026-01-03'):
            for scenario in ('trend_with', 'reversal_with', 'chop', 'reversal_against', 'trend_against'):
                trade = self.trade('US.AAA', 'LONG', .2)
                trade.update(trade_date=day, scenario=scenario)
                rows.append(trade)
        result = paired_intervals(rows, rows)
        self.assertEqual(result['invalid_draws'], 0)
        self.assertEqual(result['interval_95'], [0, 0])
