import unittest

from studies.trader_replication.martin_continue_bn import classify


class RetryTiming(unittest.TestCase):
    def test_five_day_boundary_and_same_day_exit_are_distinct(self):
        days = [f'2024-01-{i:02d}' for i in range(1, 18)]
        index = {day: i for i, day in enumerate(days)}
        def trade(entry, exit_, ret):
            return {'code': 'A', 'kind': 'list', 'entry': days[entry], 'exit': days[exit_], 'ret': ret, 'why': 'stop'}
        trades = [trade(0, 1, -.1), trade(6, 7, .2), trade(7, 8, -.1), trade(14, 15, -.1)]
        self.assertEqual([category for category, _ in classify(trades, index)],
                         ['other', 'after_loss', 'same_day_exit', 'other'])
