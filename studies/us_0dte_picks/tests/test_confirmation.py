"""R28 mechanics; synthetic paths exercise confirmation, not performance."""
import unittest
from unittest.mock import patch

from custody.evaluate import _force_entry
from custody.tests.helpers import BASE_PARAMS, path_bars, session
from studies.us_0dte_picks.confirmation import MultiConfirmation, validate_confirmation


def params(mode='window', count=2, span=5):
    key = 'confirmation_bar_minutes' if mode == 'higher' else 'confirmation_window_minutes'
    return {**BASE_PARAMS, 'confirmation_mode': mode, 'confirmation_count': count, key: span}


class ConfirmationTests(unittest.TestCase):
    def replay(self, mode, count, span, signals, direction='LONG', omit=(), closes=None):
        sign = 1 if direction == 'LONG' else -1
        bars = path_bars(closes or [100 + sign * 0.2 * i for i in range(30)])
        engine = MultiConfirmation(params(mode, count, span), direction, session(), 100)
        with patch.object(engine, '_raw_entry_reason', side_effect=lambda b, m: 'trend_breakout' if m in signals else None):
            actions = {i: engine.on_bar(b).action for i, b in enumerate(bars, 1) if i not in omit}
        return actions, engine

    def test_window_accepts_nonadjacent_signals_symmetrically(self):
        for direction in ('LONG', 'SHORT'):
            actions, _ = self.replay('window', 2, 5, {15, 17}, direction)
            self.assertEqual(actions[15], 'WAIT')
            self.assertEqual(actions[16], 'WAIT')
            self.assertEqual(actions[17], 'ENTER')
            actions, _ = self.replay('window', 3, 10, {15, 18, 23}, direction)
            self.assertEqual(actions[22], 'WAIT')
            self.assertEqual(actions[23], 'ENTER')

    def test_window_expiry_and_gaps_remove_old_evidence(self):
        actions, _ = self.replay('window', 2, 5, {15, 20, 22})
        self.assertEqual(actions[20], 'WAIT')
        self.assertEqual(actions[22], 'ENTER')
        actions, _ = self.replay('window', 2, 5, {15, 17, 19}, omit={16})
        self.assertEqual(actions[17], 'WAIT')
        self.assertEqual(actions[19], 'ENTER')

    def test_direction_failure_clears_events(self):
        closes = [100 + 0.2 * i for i in range(30)]
        closes[15] = 95
        actions, _ = self.replay('window', 2, 5, {15, 17, 19}, closes=closes)
        self.assertEqual(actions[17], 'WAIT')
        self.assertEqual(actions[19], 'ENTER')

    def test_episodes_require_a_false_bar_between_events(self):
        actions, _ = self.replay('episode', 2, 15, {15, 16, 17, 19})
        self.assertEqual(actions[17], 'WAIT')
        self.assertEqual(actions[19], 'ENTER')
        actions, _ = self.replay('episode', 2, 5, {15, 20})
        self.assertNotIn('ENTER', actions.values())

    def test_higher_bars_are_complete_nonoverlapping_and_symmetric(self):
        for period in (3, 5):
            for direction in ('LONG', 'SHORT'):
                actions, _ = self.replay('higher', 2, period, set(range(2, 31)), direction)
                self.assertEqual(actions[2 * period - 1], 'WAIT')
                self.assertEqual(actions[2 * period], 'ENTER')
                # A missing constituent bar invalidates its block and all prior votes.
                actions, _ = self.replay('higher', 2, period, set(range(2, 31)), direction, omit={period + 1})
                self.assertEqual(actions[3 * period], 'WAIT')
                self.assertEqual(actions[4 * period], 'ENTER')

    def test_current_raw_signal_is_required_even_after_higher_confirmation(self):
        actions, _ = self.replay('higher', 2, 3, {8})
        self.assertEqual(actions[6], 'WAIT')
        self.assertEqual(actions[8], 'ENTER')

    def test_a_failed_completed_block_must_age_out_before_entry(self):
        closes = [100, 100.2, 100.4, 100.6, 100.8, 100.3, 100.6, 100.9, 101.2,
                  101.5, 101.8, 102.1]
        for direction in ('LONG', 'SHORT'):
            path = closes if direction == 'LONG' else [200 - c for c in closes]
            actions, _ = self.replay('higher', 2, 3, set(range(1, 13)), direction, closes=path)
            self.assertEqual(actions[6], 'WAIT')
            self.assertEqual(actions[9], 'WAIT')
            self.assertEqual(actions[11], 'WAIT')
            self.assertEqual(actions[12], 'ENTER')

    def test_random_control_bypasses_confirmation(self):
        for mode in ('window', 'episode', 'higher'):
            engine = _force_entry(MultiConfirmation(params(mode), 'LONG', session(), 100), 5)
            actions = [engine.on_bar(b).action for b in path_bars([100.0] * 6)]
            self.assertEqual(actions, ['WAIT'] * 4 + ['ENTER'] * 2)

    def test_parameter_validation_and_duplicate_bars(self):
        for change in ({'confirmation_count': True}, {'confirmation_count': 2.5},
                       {'confirmation_window_minutes': 1}, {'confirmation_mode': 'unknown'},
                       {'entry_confirm_minutes': 2}, {'confirmation_bar_minutes': 3}):
            with self.assertRaises(ValueError):
                validate_confirmation({**params(), **change})
        engine = MultiConfirmation(params(), 'LONG', session(), 100)
        bar = path_bars([100])[0]
        engine.on_bar(bar)
        with self.assertRaises(ValueError):
            engine.on_bar(bar)


if __name__ == '__main__':
    unittest.main()
