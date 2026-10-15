"""R27 mechanics on synthetic bars; never used as performance evidence."""
import unittest
from dataclasses import replace
from unittest.mock import patch

from custody.engines.zero_dte_timing import ZeroDteTiming, validate_params
from custody.evaluate import _force_entry
from custody.tests.helpers import BASE_PARAMS, path_bars, session


class EntryConfirmationTests(unittest.TestCase):
    def test_full_signal_streak_resets_on_failure_and_missing_minute(self):
        bars = path_bars([100 + i * 0.1 for i in range(10)])
        for count in (2, 3):
            engine = ZeroDteTiming({**BASE_PARAMS, 'entry_confirm_minutes': count}, 'LONG', session(), 100)
            # A failure interrupts the first streak; a missing minute interrupts the next.
            chosen = [bars[i] for i in (0, 1, 2, 4, 5, 6)]
            with patch.object(engine, '_raw_entry_reason', side_effect=['trend_breakout', None] + ['trend_breakout'] * 4):
                actions = [engine.on_bar(b).action for b in chosen]
            expected = ['WAIT'] * (4 if count == 2 else 5)
            self.assertEqual(actions, expected + ['ENTER'] * (6 - len(expected)))

    def test_real_conditions_delay_both_directions_and_keep_pending_entry(self):
        for direction, sign in (('LONG', 1), ('SHORT', -1)):
            bars = path_bars([100 + sign * 0.2 * i for i in range(25)])
            firsts = []
            for count in (1, 2, 3):
                engine = ZeroDteTiming({**BASE_PARAMS, 'entry_confirm_minutes': count}, direction, session(), 100)
                actions = [engine.on_bar(b).action for b in bars]
                firsts.append(actions.index('ENTER'))
                self.assertTrue(all(a == 'ENTER' for a in actions[firsts[-1]:]))
            self.assertEqual(firsts, [14, 15, 16])

    def test_strength_filters_each_minute_and_volume_excludes_current_bar(self):
        for direction, sign in (('LONG', 1), ('SHORT', -1)):
            bars = path_bars([100 + sign * 0.2 * i for i in range(17)])
            params = {**BASE_PARAMS, 'entry_confirm_minutes': 2,
                      'min_breakout_volume_ratio': 1.0, 'min_close_location': 0.75}
            # Minute 16 breaks volume confirmation despite keeping price direction.
            bars[15] = replace(bars[15], volume=999)
            engine = ZeroDteTiming(params, direction, session(), 100)
            actions = [engine.on_bar(b).action for b in bars]
            self.assertNotIn('ENTER', actions)
            self.assertEqual(engine.entry_signal_streak, 1)
            # Exactly the favourable quartile passes; just outside fails.
            for location, expected in ((0.75, 'ENTER'), (0.749, 'WAIT')):
                engine = ZeroDteTiming({**params, 'entry_confirm_minutes': 1}, direction, session(), 100)
                for b in bars[:14]:
                    engine.on_bar(b)
                b = bars[14]
                low = b.close - (location if sign == 1 else 1 - location)
                b = replace(b, low=low, high=low + 1.0)
                self.assertEqual(engine.on_bar(b).action, expected)

    def test_invalid_parameters_and_no_late_confirmation_entry(self):
        for changes in ({'entry_confirm_minutes': 0}, {'entry_confirm_minutes': 2.5},
                        {'entry_confirm_minutes': True}, {'min_close_location': 1.1}):
            with self.assertRaises(ValueError):
                validate_params({**BASE_PARAMS, **changes})
        engine = ZeroDteTiming({**BASE_PARAMS, 'entry_confirm_minutes': 2}, 'LONG', session(), 100)
        bars = path_bars([100.0] * 376)
        with patch.object(engine, '_raw_entry_reason', return_value='trend_breakout'):
            self.assertEqual(engine.on_bar(bars[373]).action, 'WAIT')
            self.assertEqual(engine.on_bar(bars[374]).action, 'WAIT')

    def test_random_entry_control_uses_its_exact_minute_without_confirmation(self):
        engine = ZeroDteTiming({**BASE_PARAMS, 'entry_confirm_minutes': 3}, 'LONG', session(), 100)
        engine = _force_entry(engine, 15)
        actions = [engine.on_bar(b).action for b in path_bars([100.0] * 16)]
        self.assertEqual(actions, ['WAIT'] * 14 + ['ENTER', 'ENTER'])


if __name__ == '__main__':
    unittest.main()
