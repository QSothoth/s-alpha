import unittest

from studies.trader_replication.martin_continue_hv import duration_stats, without_partial
from studies.trader_replication.system import Rules


class HoldWinnersTest(unittest.TestCase):
    def test_only_fixed_partial_changes_and_adds_remain(self):
        rules = Rules(trims=(10,), trim_frac=.3, trail='e21', trail_next_open=True,
                      add_next_open=True, management_by_kind={'list': {'add_levels': (1, 3)}})
        new = without_partial(rules)
        self.assertEqual(new.trims, ())
        self.assertEqual(new.trail, rules.trail)
        self.assertEqual(new.management_by_kind, rules.management_by_kind)
        self.assertEqual(new.add_next_open, rules.add_next_open)
        self.assertEqual(rules.trims, (10,))

    def test_kind_partial_override_is_not_silently_kept(self):
        rules = Rules(trims=(10,), trail='e21', management_by_kind={'list': {'trims': (3,)}})
        with self.assertRaises(ValueError):
            without_partial(rules)

    def test_winner_duration_excludes_open_positions(self):
        trades = [dict(entry='2025-01-02', why='trail_open', ret_invested=.6, days=50),
                  dict(entry='2025-02-03', why='stop', ret_invested=-.02, days=0),
                  dict(entry='2025-03-01', why='end', ret_invested=.8, days=90)]
        stats = duration_stats(trades)['2025']
        self.assertEqual(stats['big30'], {'n': 1, 'median_days': 50})
        self.assertEqual(stats['big50'], {'n': 1, 'median_days': 50})
        self.assertEqual(stats['loss'], {'n': 1, 'median_days': 0})


if __name__ == '__main__':
    unittest.main()
