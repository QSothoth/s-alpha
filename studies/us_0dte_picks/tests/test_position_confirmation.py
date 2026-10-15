"""Synthetic mechanics only, never performance evidence."""
import unittest
from unittest.mock import patch

from custody.engines.zero_dte_timing import ZeroDteTiming
from custody.tests.helpers import BASE_PARAMS, path_bars, session
from studies.us_0dte_picks.position_confirmation import BlockConfirmation, PositionConfirmation


class PositionTests(unittest.TestCase):
    def test_complete_blocks_current_support_gap_and_mirror(self):
        for sign in (1, -1):
            bars = path_bars([100 + sign * n for n in range(12)])
            c = BlockConfirmation(3)
            for minute, bar in enumerate(bars[:6], 1):
                direction = c.update(bar, minute, bar.close - sign, 100 + sign, 100)
                self.assertEqual(direction, sign if minute == 6 else 0)
            self.assertEqual(c.update(bars[6], 7, bars[6].close + sign, 100 + sign, 100), 0)
            self.assertEqual(c.update(bars[8], 9, bars[8].close - sign, 100 + sign, 100), 0)
            self.assertEqual(len(c.votes), 0)

    def engine(self, policy='HX'):
        e = PositionConfirmation({**BASE_PARAMS, 'combo_policy': policy, 'combo_period': 3,
                                  'take_profit_premium': 1, 'profit_lock_at': .5, 'profit_lock_keep': .5},
                                 'LONG', session(), 100)
        for b in path_bars([100 + .1 * n for n in range(20)]):
            d = e.on_bar(b)
            if d.action == 'ENTER' and e.phase == 'ENTERING':
                e.on_entry_filled(b.close_time, b.close)
        self.assertEqual(e.phase, 'IN')
        return e

    def test_holding_overlay_restores_parameters_and_preserves_lock(self):
        e = self.engine('H')
        e.confirmation.direction = 1
        with patch.object(e, '_observe'), patch.object(e, '_premium', return_value=e.entry_value * 2.2):
            self.assertEqual(e._manage(21).action, 'HOLD')
        self.assertEqual(e.p['take_profit_premium'], 1)
        self.assertEqual(e.p['fail_minutes'], BASE_PARAMS['fail_minutes'])
        with patch.object(e, '_observe'), patch.object(e, '_premium', return_value=e.entry_value * 1.3):
            self.assertEqual(e._manage(22).reason, 'profit_lock')

    def test_opposite_exit_and_risk_priority(self):
        for risk in (False, True):
            e = self.engine('X')
            e.confirmation.direction = -1
            if risk:
                e.stop = e.ind.close + 1
            with patch.object(e, '_observe'):
                decision = e._manage(21)
            self.assertEqual(decision.action, 'EXIT')
            if risk:
                self.assertIn(decision.reason, ('invalidation_stop', 'trailing_stop', 'breakeven_stop'))
            else:
                self.assertEqual(decision.reason, 'strong_reversal')

    def test_scheduled_flatten_cannot_be_deferred(self):
        e = self.engine('HX')
        e.confirmation.direction = 1
        decision = e.on_bar(path_bars([102] * 375)[-1])
        self.assertEqual(decision.reason, 'scheduled_flatten')
        self.assertEqual(e.on_bar(path_bars([102] * 376)[-1]).action, 'EXIT')

    def test_entries_match_and_random_override_still_observes(self):
        for direction in ('LONG', 'SHORT'):
            for deadline in (None, 60):
                params = {**BASE_PARAMS, 'must_enter_by_minute': deadline}
                original = ZeroDteTiming(params, direction, session(), 100)
                new = PositionConfirmation({**params, 'combo_policy': 'HX', 'combo_period': 3}, direction, session(), 100)
                for bar in path_bars([100 + n * .01 for n in range(80)]):
                    self.assertEqual(original.on_bar(bar), new.on_bar(bar))
                self.assertEqual(new.confirmation.minute, 80)
        e = PositionConfirmation({**BASE_PARAMS, 'combo_policy': 'HX', 'combo_period': 3}, 'LONG', session(), 100)
        e._entry_reason = lambda bar, minute: 'random_entry' if minute == 10 else None
        for bar in path_bars([100 + n * .01 for n in range(15)]):
            e.on_bar(bar)
        self.assertEqual(e.entry_reason, 'random_entry')
        self.assertEqual(e.confirmation.minute, 15)


if __name__ == '__main__':
    unittest.main()
